"""The CI sample round trip: export a window from one lake, load it into an empty one."""

from datetime import UTC, datetime

import pytest
from pyiceberg.catalog.sql import SqlCatalog

from gridpulse_ingestion import sample
from gridpulse_ingestion.eia.routes import ROUTES
from gridpulse_ingestion.storage import IcebergSink, run_record

T = lambda d, h=0: datetime(2026, 10, d, h, tzinfo=UTC)  # noqa: E731


def sink(tmp_path, name: str) -> IcebergSink:
    warehouse = tmp_path / name
    warehouse.mkdir()
    catalog = SqlCatalog(
        name, uri=f"sqlite:///{warehouse}/catalog.db", warehouse=f"file://{warehouse}"
    )
    return IcebergSink(catalog, "raw")


def region_row(day: int, value: str, run: str) -> dict:
    period = T(day, 5)
    return {
        "period": period.strftime("%Y-%m-%dT%H"),
        "period_utc": period,
        **{c: None for c in ROUTES["region-data"].columns},
        "respondent": "PJM",
        "type": "D",
        "value": value,
        "_extra": None,
        "_record_hash": f"h{value}",
        "_run_id": run,
        "_route": "region-data",
        "_ingested_at": T(day, 7),
    }


@pytest.fixture
def source(tmp_path) -> IcebergSink:
    lake = sink(tmp_path, "source")
    route = ROUTES["region-data"]
    # Inside the window: two versions of one value (a revision). Outside: one row each side.
    lake.append(
        route,
        [
            region_row(5, "1", "r0"),
            region_row(6, "2", "r1"),
            region_row(6, "3", "r2"),
            region_row(9, "4", "r3"),
        ],
    )
    manifest = {
        "run_id": "r1",
        "route": "region-data",
        "started_at": T(6, 7).isoformat(),
        "status": "succeeded",
        "window_start_utc": T(6).isoformat(),
        "window_end_utc": T(7).isoformat(),
    }
    late = {
        **manifest,
        "run_id": "r9",
        "window_start_utc": T(9).isoformat(),
        "window_end_utc": T(10).isoformat(),
    }
    lake.append_runs([run_record(manifest, T(6, 8)), run_record(late, T(9, 8))])
    return lake


def test_export_keeps_the_window_and_load_rebuilds_it(source, tmp_path):
    out = tmp_path / "ci-sample"
    exported = sample.export(source, out, T(6), T(8))
    assert exported == {"eia_region_data": 2, "ingestion_runs": 1}  # missing tables skipped
    target = sink(tmp_path, "target")
    assert sample.load(target, out) == exported
    rows = target.existing("eia_region_data").scan().to_arrow().to_pylist()
    assert sorted(r["value"] for r in rows) == ["2", "3"]  # both versions kept
    assert {r["period_utc"] for r in rows} == {T(6, 5)}
    (run,) = target.existing("ingestion_runs").scan().to_arrow().to_pylist()
    assert run["run_id"] == "r1"


def test_export_is_deterministic(source, tmp_path):
    first, second = tmp_path / "a", tmp_path / "b"
    sample.export(source, first, T(6), T(8))
    sample.export(source, second, T(6), T(8))
    for f in first.iterdir():
        assert f.read_bytes() == (second / f.name).read_bytes()
