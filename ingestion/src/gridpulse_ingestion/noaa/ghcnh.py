"""NOAA GHCNh (Global Historical Climatology Network hourly) station observations.

GHCNh replaced the Integrated Surface Database (ISD / Global Hourly), which stopped updating in
August 2025 (ADR-0004). It is read from the public AWS Open Data bucket `noaa-ghcnh-pds`
without credentials: one Parquet file per station and year, rewritten as NOAA appends new
observations (about a 1.5-day lag). Values are already in SI units (°C, m/s), and a missing
element is null. A station reports several times an hour (routine METAR at :51, synoptic at
:00, specials); every report is kept here and staging picks one per hour.
"""

import hashlib
import io
import json
import re
from collections.abc import Sequence
from datetime import UTC, datetime

import pyarrow as pa
import pyarrow.parquet as pq

BUCKET = "noaa-ghcnh-pds"
ROUTE_NAME = "noaa-ghcnh"
STATION_ID = re.compile(r"^[A-Z0-9]{11}$")
MISSING_SENTINEL = -9999.0

# Source column -> raw table column. Measurements keep NOAA's units and types; the quality
# code and report type travel with temperature, the element the platform uses.
SOURCE_COLUMNS = {
    "STATION": "station_id",
    "Station_name": "station_name",
    "Year": "year",
    "Month": "month",
    "Day": "day",
    "Hour": "hour",
    "Minute": "minute",
    "temperature": "temperature_c",
    "temperature_Quality_Code": "temperature_quality_code",
    "temperature_Report_Type": "report_type",
    "dew_point_temperature": "dew_point_c",
    "wind_speed": "wind_speed_ms",
    "relative_humidity": "relative_humidity_pct",
}
HASH_FIELDS = (
    "station_id",
    "observed_at_utc",
    "report_type",
    "temperature_c",
    "temperature_quality_code",
    "dew_point_c",
    "wind_speed_ms",
    "relative_humidity_pct",
)


def station_year_key(station_id: str, year: int) -> str:
    if not STATION_ID.match(station_id):
        raise ValueError(f"not a GHCNh station id: {station_id!r}")
    return f"hourly/access/by-year/{year}/parquet/GHCNh_{station_id}_{year}.parquet"


def read_station_year(s3, station_id: str, year: int) -> pa.Table | None:
    """The station's file for a year, or None when NOAA has no file for it."""
    try:
        body = s3.get_object(Bucket=BUCKET, Key=station_year_key(station_id, year))["Body"].read()
    except s3.exceptions.NoSuchKey:
        return None
    return pq.read_table(io.BytesIO(body), columns=list(SOURCE_COLUMNS))


def _number(value) -> float | None:
    if value is None or value == "":
        return None
    number = float(value)
    return None if number <= MISSING_SENTINEL else number


def record_hash(record: dict) -> str:
    payload = json.dumps([record.get(f) for f in HASH_FIELDS], default=str, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def to_records(
    table: pa.Table,
    start: datetime,
    end: datetime,
    *,
    run_id: str,
    ingested_at: datetime,
) -> list[dict]:
    """Observations with a temperature in [start, end), shaped for the raw Iceberg table."""
    records = []
    for row in table.rename_columns([SOURCE_COLUMNS[c] for c in table.column_names]).to_pylist():
        observed = datetime(
            int(row["year"]), int(row["month"]), int(row["day"]),
            int(row["hour"]), int(row["minute"]), tzinfo=UTC,
        )  # fmt: skip
        temperature = _number(row["temperature_c"])
        if not start <= observed < end or temperature is None:
            continue
        record = {
            "station_id": row["station_id"],
            "station_name": row["station_name"],
            "observed_at_utc": observed,
            "report_type": row["report_type"],
            "temperature_c": temperature,
            "temperature_quality_code": row["temperature_quality_code"],
            "dew_point_c": _number(row["dew_point_c"]),
            "wind_speed_ms": _number(row["wind_speed_ms"]),
            "relative_humidity_pct": _number(row["relative_humidity_pct"]),
        }
        record |= {
            "_record_hash": record_hash(record),
            "_run_id": run_id,
            "_route": ROUTE_NAME,
            "_ingested_at": ingested_at,
        }
        records.append(record)
    return records


def years(start: datetime, end: datetime) -> Sequence[int]:
    """Calendar years touched by [start, end)."""
    last = end.year if (end.month, end.day, end.hour, end.minute) != (1, 1, 0, 0) else end.year - 1
    return range(start.year, last + 1)
