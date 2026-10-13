"""A small slice of the raw lake, committed to the repo, so CI can build dbt on real data.

`export` copies the rows of every raw table inside a UTC window from a running lake to Parquet
files (one per table); `load` appends those files to the raw tables of another lake (in CI, a
fresh local one) through the same sink, schemas and partitioning as the extractor. EIA and NOAA
data are public.

    gridpulse-extract sample export --start 2026-09-28 --end 2026-10-13 --dir local/ci-sample
    gridpulse-extract sample load --dir local/ci-sample
"""

from datetime import datetime
from pathlib import Path

import pyarrow.parquet as pq
from pyiceberg.exceptions import NoSuchTableError
from pyiceberg.expressions import And, BooleanExpression, GreaterThanOrEqual, LessThan

from gridpulse_ingestion.eia.routes import ROUTES
from gridpulse_ingestion.storage import (
    NOAA_TABLE,
    RUNS_TABLE,
    IcebergSink,
    noaa_table_schema,
    raw_table_name,
    raw_table_schema,
    runs_table_schema,
)

# table -> (schema, partition column, how to select the window)
TABLES = {
    **{
        raw_table_name(route): (raw_table_schema(route), "period_utc", "period_utc")
        for route in ROUTES.values()
    },
    NOAA_TABLE: (noaa_table_schema(), "observed_at_utc", "observed_at_utc"),
    # Runs whose requested window overlaps ours (NOAA runs ask for days, EIA runs for hours).
    RUNS_TABLE: (runs_table_schema(), "started_at", None),
}


def _window(column: str | None, start: datetime, end: datetime) -> BooleanExpression:
    s, e = start.isoformat(), end.isoformat()
    if column is None:
        return And(LessThan("window_start_utc", e), GreaterThanOrEqual("window_end_utc", s))
    return And(GreaterThanOrEqual(column, s), LessThan(column, e))


def export(sink: IcebergSink, directory: Path, start: datetime, end: datetime) -> dict[str, int]:
    """Rows per table written to `directory/<table>.parquet` (tables that don't exist: skipped)."""
    directory.mkdir(parents=True, exist_ok=True)
    counts = {}
    for name, (_, _, column) in TABLES.items():
        try:
            table = sink.existing(name)
        except NoSuchTableError:
            continue
        rows = table.scan(row_filter=_window(column, start, end)).to_arrow()
        # Stable order, so a re-export of the same data gives the same file.
        keys = [c for c in ("_ingested_at", "_record_hash", "run_id") if c in rows.column_names]
        rows = rows.sort_by([(k, "ascending") for k in keys])
        pq.write_table(rows, directory / f"{name}.parquet", compression="zstd")
        counts[name] = rows.num_rows
    return counts


def load(sink: IcebergSink, directory: Path) -> dict[str, int]:
    """Append every `<table>.parquet` in `directory` to that raw table (created if missing)."""
    counts = {}
    for name, (schema, month_of, _) in TABLES.items():
        path = directory / f"{name}.parquet"
        if not path.exists():
            continue
        table = sink.ensure(name, schema, month_of)
        rows = pq.read_table(path).cast(table.schema().as_arrow())
        table.append(rows)
        counts[name] = rows.num_rows
    return counts
