"""Where extracted data goes: untouched API responses in S3, validated rows in raw Iceberg."""

import gzip
import json
from collections.abc import Sequence
from datetime import datetime

import boto3
import pyarrow as pa
from pyiceberg.catalog import Catalog, load_catalog
from pyiceberg.exceptions import NoSuchTableError
from pyiceberg.partitioning import PartitionField, PartitionSpec
from pyiceberg.schema import Schema
from pyiceberg.table import Table
from pyiceberg.transforms import MonthTransform
from pyiceberg.types import DoubleType, LongType, NestedField, StringType, TimestamptzType

from gridpulse_ingestion.config import Settings
from gridpulse_ingestion.eia.routes import Route

META_COLUMNS = ("_extra", "_record_hash", "_run_id", "_route", "_ingested_at", "_api_version")


class RawStore:
    """Raw responses and run manifests, laid out as in the blueprint:

    eia/route=<route>/ingest_date=<date>/run_id=<id>/page=0001.json.gz
    _manifests/route=<route>/ingest_date=<date>/run_id=<id>/attempt=<started_at>.json

    Pages are overwritten by a rerun of the same window (deterministic). Manifests are kept
    per attempt, so a failed attempt stays on record after a successful retry.
    """

    def __init__(self, s3_client, bucket: str) -> None:
        self._s3 = s3_client
        self.bucket = bucket

    @classmethod
    def from_settings(cls, settings: Settings) -> "RawStore":
        secret = settings.s3_secret_key.get_secret_value() if settings.s3_secret_key else None
        client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=secret,
        )
        return cls(client, settings.raw_bucket)

    @staticmethod
    def page_key(route: str, ingest_date: str, run_id: str, page: int) -> str:
        return (
            f"eia/route={route}/ingest_date={ingest_date}/run_id={run_id}/page={page:04d}.json.gz"
        )

    @staticmethod
    def manifest_key(route: str, ingest_date: str, run_id: str, started_at: datetime) -> str:
        attempt = started_at.strftime("%Y%m%dT%H%M%S%fZ")
        return (
            f"_manifests/route={route}/ingest_date={ingest_date}/run_id={run_id}/"
            f"attempt={attempt}.json"
        )

    def put_page(self, key: str, raw: bytes) -> None:
        # mtime=0 makes the gzip bytes deterministic, so reruns write identical objects.
        body = gzip.compress(raw, mtime=0)
        self._s3.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=body,
            ContentType="application/json",
            ContentEncoding="gzip",
        )

    @staticmethod
    def watermark_key(route: str, facets: Sequence[str]) -> str:
        scope = ",".join(sorted(facets)) or "all"
        return f"_state/route={route}/facets={scope}/watermark.json"

    def get_watermark(self, route: str, facets: Sequence[str]) -> datetime | None:
        """End of the latest window loaded successfully for this route and BA set, or None."""
        try:
            obj = self._s3.get_object(Bucket=self.bucket, Key=self.watermark_key(route, facets))
        except self._s3.exceptions.NoSuchKey:
            return None
        return datetime.fromisoformat(json.loads(obj["Body"].read())["loaded_through_utc"])

    def advance_watermark(self, route: str, facets: Sequence[str], window_end: datetime) -> None:
        """Move the watermark forward only (a backfill of old hours never moves it back)."""
        current = self.get_watermark(route, facets)
        if current is not None and current >= window_end:
            return
        body = json.dumps({"loaded_through_utc": window_end.isoformat()}).encode()
        self._s3.put_object(
            Bucket=self.bucket,
            Key=self.watermark_key(route, facets),
            Body=body,
            ContentType="application/json",
        )

    def iter_manifests(self):
        """Every run manifest in the raw bucket (for backfilling ingestion_runs)."""
        paginator = self._s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix="_manifests/"):
            for obj in page.get("Contents", []):
                body = self._s3.get_object(Bucket=self.bucket, Key=obj["Key"])["Body"].read()
                yield json.loads(body)

    def put_manifest(self, key: str, manifest: dict) -> None:
        body = json.dumps(manifest, indent=2, sort_keys=True, default=str).encode()
        self._s3.put_object(Bucket=self.bucket, Key=key, Body=body, ContentType="application/json")


RUNS_TABLE = "ingestion_runs"
_RUN_COLUMNS = [
    ("run_id", StringType(), True),
    ("route", StringType(), True),
    ("started_at", TimestamptzType(), True),
    ("status", StringType(), True),
    ("window_start_utc", TimestamptzType(), False),
    ("window_end_utc", TimestamptzType(), False),
    ("scope", StringType(), False),
    ("pages", LongType(), False),
    ("rows_expected", LongType(), False),
    ("rows_received", LongType(), False),
    ("rows_appended", LongType(), False),
    ("duration_seconds", DoubleType(), False),
    ("error", StringType(), False),
    ("details", StringType(), False),
    ("_ingested_at", TimestamptzType(), True),
]


def runs_table_schema() -> Schema:
    """One row per extraction attempt, mirroring the S3 run manifest."""
    return Schema(
        *(
            NestedField(field_id=i, name=name, field_type=kind, required=required)
            for i, (name, kind, required) in enumerate(_RUN_COLUMNS, start=1)
        )
    )


def run_record(manifest: dict, appended_at: datetime) -> dict:
    """Flatten a run manifest into an ingestion_runs row. Fields without a column (warnings,
    unknown fields, missing stations, ...) go to `details` as JSON, so nothing is lost."""

    def ts(value):
        return datetime.fromisoformat(value) if isinstance(value, str) else value

    columns = {name for name, _, _ in _RUN_COLUMNS}
    scope = manifest.get("facets", manifest.get("stations"))
    details = {
        k: v for k, v in manifest.items() if k not in columns and k not in ("facets", "stations")
    }
    return {
        "run_id": manifest["run_id"],
        "route": manifest["route"],
        "started_at": ts(manifest["started_at"]),
        "status": manifest["status"],
        "window_start_utc": ts(manifest.get("window_start_utc")),
        "window_end_utc": ts(manifest.get("window_end_utc")),
        "scope": json.dumps(scope) if scope is not None else None,
        "pages": manifest.get("pages"),
        "rows_expected": manifest.get("rows_expected"),
        "rows_received": manifest.get("rows_received"),
        "rows_appended": manifest.get("rows_appended"),
        "duration_seconds": manifest.get("duration_seconds"),
        "error": manifest.get("error"),
        "details": json.dumps(details, sort_keys=True, default=str) if details else None,
        "_ingested_at": appended_at,
    }


def raw_table_schema(route: Route) -> Schema:
    """period (as received) + period_utc + the route's columns + pipeline metadata."""
    names = ["period", "period_utc", *route.columns, *META_COLUMNS]
    required = {"period", "period_utc", "_record_hash", "_run_id", "_route", "_ingested_at"}
    timestamps = {"period_utc", "_ingested_at"}
    fields = [
        NestedField(
            field_id=i,
            name=name,
            field_type=TimestamptzType() if name in timestamps else StringType(),
            required=name in required,
        )
        for i, name in enumerate(names, start=1)
    ]
    return Schema(*fields)


def raw_table_name(route: Route) -> str:
    return "eia_" + route.name.replace("-", "_")


NOAA_TABLE = "noaa_ghcnh_observations"


def noaa_table_schema() -> Schema:
    """GHCNh observations as read (one row per station report), plus pipeline metadata."""
    columns = [
        ("station_id", StringType(), True),
        ("station_name", StringType(), False),
        ("observed_at_utc", TimestamptzType(), True),
        ("report_type", StringType(), False),
        ("temperature_c", DoubleType(), False),
        ("temperature_quality_code", StringType(), False),
        ("dew_point_c", DoubleType(), False),
        ("wind_speed_ms", DoubleType(), False),
        ("relative_humidity_pct", DoubleType(), False),
        ("_record_hash", StringType(), True),
        ("_run_id", StringType(), True),
        ("_route", StringType(), True),
        ("_ingested_at", TimestamptzType(), True),
    ]
    return Schema(
        *(
            NestedField(field_id=i, name=name, field_type=kind, required=required)
            for i, (name, kind, required) in enumerate(columns, start=1)
        )
    )


class IcebergSink:
    """Appends validated rows to `<raw_namespace>.eia_<route>`.

    Append-only: history is never rewritten.
    """

    def __init__(self, catalog: Catalog, namespace: str) -> None:
        self._catalog = catalog
        self._namespace = namespace

    @classmethod
    def from_settings(cls, settings: Settings) -> "IcebergSink":
        props = {
            "type": settings.catalog_type,
            "py-io-impl": "pyiceberg.io.pyarrow.PyArrowFileIO",
            **settings.s3_properties(),
        }
        if settings.catalog_type == "rest":
            props |= {"uri": settings.catalog_uri, "warehouse": settings.catalog_warehouse}
        else:  # glue: table locations come from the Glue database's location_uri
            props |= {"glue.region": settings.s3_region, "client.region": settings.s3_region}
        return cls(load_catalog("gridpulse", **props), settings.raw_namespace)

    def _table(self, name: str, schema: Schema, month_of: str) -> Table:
        """Load the table, or create it partitioned by month of the `month_of` column."""
        identifier = (self._namespace, name)
        try:
            return self._catalog.load_table(identifier)
        except NoSuchTableError:
            pass
        self._catalog.create_namespace_if_not_exists(self._namespace)
        spec = PartitionSpec(
            PartitionField(
                source_id=schema.find_field(month_of).field_id,
                field_id=1000,
                transform=MonthTransform(),
                name=f"{month_of}_month",
            )
        )
        return self._catalog.create_table_if_not_exists(
            identifier, schema=schema, partition_spec=spec
        )

    def table(self, route: Route) -> Table:
        return self._table(raw_table_name(route), raw_table_schema(route), "period_utc")

    @staticmethod
    def _append(table: Table, records: Sequence[dict]) -> int:
        if not records:
            return 0
        arrow = pa.Table.from_pylist(list(records), schema=table.schema().as_arrow())
        table.append(arrow)
        return arrow.num_rows

    def append(self, route: Route, records: Sequence[dict]) -> int:
        if not records:
            return 0
        return self._append(self.table(route), records)

    def append_runs(self, records: Sequence[dict]) -> int:
        if not records:
            return 0
        return self._append(self._table(RUNS_TABLE, runs_table_schema(), "started_at"), records)

    def append_noaa(self, records: Sequence[dict]) -> int:
        if not records:
            return 0
        return self._append(
            self._table(NOAA_TABLE, noaa_table_schema(), "observed_at_utc"), records
        )


def ingest_date(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%d")
