"""One extraction run: fetch a window, keep raw pages, validate rows, append, write a manifest.

Runs are deterministic: `run_id` comes from route + window + facets, so a rerun writes the same
raw keys and the same record hashes. Rows are appended (never overwritten); exact duplicates
from reruns are removed by `_record_hash` in dbt staging.
"""

import hashlib
import json
import logging
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta

from pydantic import ValidationError

from gridpulse_ingestion.eia.client import EIAClient
from gridpulse_ingestion.eia.routes import Route
from gridpulse_ingestion.noaa import ghcnh
from gridpulse_ingestion.storage import IcebergSink, RawStore, ingest_date, run_record

log = logging.getLogger(__name__)


def resolve_auto_start(
    end: datetime,
    watermark: datetime | None,
    lookback: timedelta,
    max_gap: timedelta,
) -> tuple[datetime, str | None]:
    """Start of an `--start auto` window, and a warning if part of a gap is left behind.

    Normally `end - lookback` (re-reading recent hours catches revisions). After downtime the
    window reaches back to the watermark so the gap is filled in one run, never more than
    `max_gap`: older gaps need an explicit backfill (chunked, through the API pool).
    """
    start = end - lookback
    if watermark is not None and watermark < start:
        start = watermark
    floor = end - max_gap
    if start < floor:
        return floor, (
            f"gap since {watermark.isoformat() if watermark else 'never'} is longer than "
            f"{max_gap}; loading from {floor.isoformat()} only. Backfill the rest explicitly."
        )
    return start, None


class RecordValidationError(RuntimeError):
    """A row broke a required rule. The whole batch fails; nothing is appended."""


def run_id_for(route: Route, start: datetime, end: datetime, facets: Sequence[str] = ()) -> str:
    key = "|".join([route.name, start.isoformat(), end.isoformat(), ",".join(sorted(facets))])
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def record_run(sink: IcebergSink, manifest: dict, appended_at: datetime) -> None:
    """Also append the manifest to raw.ingestion_runs for fct_ingestion_runs. Best effort: the
    S3 manifest is the record, and `gridpulse-extract manifests` can backfill a missed row."""
    try:
        sink.append_runs([run_record(manifest, appended_at)])
    except Exception:
        log.warning("could not append run %s to ingestion_runs", manifest["run_id"], exc_info=True)


def record_hash(route: Route, row: dict) -> str:
    payload = json.dumps([row.get(f) for f in route.hash_fields], separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def to_record(route: Route, raw_row: dict, *, run_id: str, ingested_at: datetime, api_version):
    try:
        row = route.model.model_validate(raw_row)
    except ValidationError as exc:
        raise RecordValidationError(f"{route.name}: invalid row {raw_row!r}: {exc}") from exc
    data = row.model_dump(include={"period", *route.columns})
    extra = row.extra_fields
    return {
        **data,
        "period_utc": row.period_utc,
        "_extra": json.dumps(extra, sort_keys=True) if extra else None,
        "_record_hash": record_hash(route, data),
        "_run_id": run_id,
        "_route": route.name,
        "_ingested_at": ingested_at,
        "_api_version": api_version,
    }


def extract(
    route: Route,
    start: datetime,
    end: datetime,
    *,
    client: EIAClient,
    raw_store: RawStore,
    sink: IcebergSink,
    facets: Sequence[str] = (),
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict:
    """Run one window end to end and return its manifest. Raises on any failure, after
    writing a manifest with status=failed so the run is still auditable."""
    started = now()
    clock = time.monotonic()
    run_id = run_id_for(route, start, end, facets)
    day = ingest_date(started)
    manifest: dict = {
        "run_id": run_id,
        "route": route.name,
        "window_start_utc": start.isoformat(),
        "window_end_utc": end.isoformat(),
        "facets": sorted(facets),
        "started_at": started.isoformat(),
        "status": "running",
        "pages": 0,
        "rows_expected": None,
        "rows_received": 0,
        "rows_appended": 0,
        "unknown_fields": [],
    }
    records: list[dict] = []
    unknown: set[str] = set()
    try:
        for page in client.fetch_window(route, start, end, facets):
            raw_store.put_page(raw_store.page_key(route.name, day, run_id, page.number), page.raw)
            manifest.update(
                pages=page.number,
                rows_expected=page.total,
                api_version=page.api_version,
                warnings=page.warnings,
            )
            for raw_row in page.rows:
                record = to_record(
                    route, raw_row, run_id=run_id, ingested_at=started, api_version=page.api_version
                )
                if record["_extra"]:
                    unknown.update(json.loads(record["_extra"]))
                records.append(record)
            manifest["rows_received"] = len(records)
        manifest["unknown_fields"] = sorted(unknown)
        manifest["rows_appended"] = sink.append(route, records)
        raw_store.advance_watermark(route.name, facets, end)
        manifest["status"] = "succeeded"
    except Exception as exc:
        manifest.update(status="failed", error=f"{type(exc).__name__}: {exc}"[:2000])
        raise
    finally:
        manifest["duration_seconds"] = round(time.monotonic() - clock, 3)
        raw_store.put_manifest(raw_store.manifest_key(route.name, day, run_id, started), manifest)
        record_run(sink, manifest, started)
    return manifest


class NoStationDataError(RuntimeError):
    """None of the requested stations has a GHCNh file for the window."""


def noaa_run_id(start: datetime, end: datetime, stations: Sequence[str]) -> str:
    key = "|".join(
        [ghcnh.ROUTE_NAME, start.isoformat(), end.isoformat(), ",".join(sorted(stations))]
    )
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def extract_noaa(
    stations: Sequence[str],
    start: datetime,
    end: datetime,
    *,
    s3,
    raw_store: RawStore,
    sink: IcebergSink,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict:
    """Load GHCNh observations for the stations and window [start, end); return the manifest.

    The source files are a public archive, so the raw copy kept here is the append-only Iceberg
    table, not a second copy of each file. A station without a file is recorded in the
    manifest (NOAA does drop stations); the run fails only if no station has data.
    """
    started = now()
    clock = time.monotonic()
    run_id = noaa_run_id(start, end, stations)
    manifest: dict = {
        "run_id": run_id,
        "route": ghcnh.ROUTE_NAME,
        "window_start_utc": start.isoformat(),
        "window_end_utc": end.isoformat(),
        "stations": sorted(stations),
        "started_at": started.isoformat(),
        "status": "running",
        "stations_missing": [],
        "rows_received": 0,
        "rows_appended": 0,
    }
    records: list[dict] = []
    try:
        for station in sorted(stations):
            found = False
            for year in ghcnh.years(start, end):
                table = ghcnh.read_station_year(s3, station, year)
                if table is None:
                    continue
                found = True
                records += ghcnh.to_records(table, start, end, run_id=run_id, ingested_at=started)
            if not found:
                manifest["stations_missing"].append(station)
        manifest["rows_received"] = len(records)
        if len(manifest["stations_missing"]) == len(stations):
            raise NoStationDataError(f"no GHCNh file for any of {sorted(stations)}")
        manifest["rows_appended"] = sink.append_noaa(records)
        raw_store.advance_watermark(ghcnh.ROUTE_NAME, stations, end)
        manifest["status"] = "succeeded"
    except Exception as exc:
        manifest.update(status="failed", error=f"{type(exc).__name__}: {exc}"[:2000])
        raise
    finally:
        manifest["duration_seconds"] = round(time.monotonic() - clock, 3)
        key = raw_store.manifest_key(ghcnh.ROUTE_NAME, ingest_date(started), run_id, started)
        raw_store.put_manifest(key, manifest)
        record_run(sink, manifest, started)
    return manifest
