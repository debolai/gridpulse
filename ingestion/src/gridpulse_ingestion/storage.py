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
from pyiceberg.types import NestedField, StringType, TimestamptzType

from gridpulse_ingestion.config import Settings
from gridpulse_ingestion.eia.routes import Route

META_COLUMNS = ("_extra", "_record_hash", "_run_id", "_route", "_ingested_at", "_api_version")


class RawStore:
    """Raw responses and run manifests, laid out as in the blueprint:

    eia/route=<route>/ingest_date=<date>/run_id=<id>/page=0001.json.gz
    _manifests/route=<route>/ingest_date=<date>/run_id=<id>.json
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
    def manifest_key(route: str, ingest_date: str, run_id: str) -> str:
        return f"_manifests/route={route}/ingest_date={ingest_date}/run_id={run_id}.json"

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

    def put_manifest(self, key: str, manifest: dict) -> None:
        body = json.dumps(manifest, indent=2, sort_keys=True, default=str).encode()
        self._s3.put_object(Bucket=self.bucket, Key=key, Body=body, ContentType="application/json")


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
        return cls(load_catalog("gridpulse", **props), settings.raw_namespace)

    def table(self, route: Route) -> Table:
        identifier = (self._namespace, raw_table_name(route))
        try:
            return self._catalog.load_table(identifier)
        except NoSuchTableError:
            pass
        self._catalog.create_namespace_if_not_exists(self._namespace)
        schema = raw_table_schema(route)
        period_utc = schema.find_field("period_utc").field_id
        spec = PartitionSpec(
            PartitionField(
                source_id=period_utc,
                field_id=1000,
                transform=MonthTransform(),
                name="period_utc_month",
            )
        )
        return self._catalog.create_table_if_not_exists(
            identifier, schema=schema, partition_spec=spec
        )

    def append(self, route: Route, records: Sequence[dict]) -> int:
        if not records:
            return 0
        table = self.table(route)
        arrow = pa.Table.from_pylist(list(records), schema=table.schema().as_arrow())
        table.append(arrow)
        return arrow.num_rows


def ingest_date(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%d")
