"""NOAA GHCNh: real recorded rows (Chicago O'Hare, 2026-10-09..10) through the reader and run."""

import io
from datetime import UTC, datetime
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from gridpulse_ingestion.noaa import ghcnh
from gridpulse_ingestion.run import NoStationDataError, extract_noaa, noaa_run_id
from gridpulse_ingestion.storage import noaa_table_schema

FIXTURE = Path(__file__).parent / "fixtures" / "noaa_ghcnh" / "GHCNh_USW00094846_2026.parquet"
STATION = "USW00094846"
START = datetime(2026, 10, 9, tzinfo=UTC)
END = datetime(2026, 10, 11, tzinfo=UTC)
NOW = datetime(2026, 10, 13, tzinfo=UTC)


@pytest.fixture
def table():
    return pq.read_table(FIXTURE)


def records(table, start=START, end=END):
    return ghcnh.to_records(table, start, end, run_id="r", ingested_at=NOW)


class FakeNoaaS3:
    """Serves the fixture for O'Hare 2026; any other station-year is missing."""

    class exceptions:
        class NoSuchKey(Exception):
            pass

    def __init__(self):
        self.keys: list[str] = []

    def get_object(self, Bucket, Key):
        assert Bucket == ghcnh.BUCKET
        self.keys.append(Key)
        if Key != ghcnh.station_year_key(STATION, 2026):
            raise self.exceptions.NoSuchKey(Key)
        return {"Body": io.BytesIO(FIXTURE.read_bytes())}


def test_keeps_every_report_with_a_temperature_in_the_window(table):
    rows = records(table)
    assert rows and all(START <= r["observed_at_utc"] < END for r in rows)
    assert all(r["temperature_c"] is not None for r in rows)
    with_temperature = [t for t in table.column("temperature").to_pylist() if t is not None]
    assert len(rows) == len(with_temperature)  # nothing else dropped
    by_hour = {}
    for r in rows:
        by_hour.setdefault(r["observed_at_utc"].replace(minute=0), []).append(r)
    assert max(len(v) for v in by_hour.values()) > 1  # several reports in some hours, all kept
    assert {r["report_type"] for r in rows} >= {"FM15"}


def test_records_match_the_raw_schema_and_hash_uniquely(table):
    rows = records(table)
    names = {f.name for f in noaa_table_schema().fields}
    assert all(set(r) == names for r in rows)
    assert len({r["_record_hash"] for r in rows}) == len(rows)
    assert records(table) == rows  # deterministic


def test_window_is_half_open(table):
    day_one = records(table, START, datetime(2026, 10, 10, tzinfo=UTC))
    day_two = records(table, datetime(2026, 10, 10, tzinfo=UTC), END)
    assert len(day_one) + len(day_two) == len(records(table))


def test_missing_sentinel_and_blank_become_null():
    assert ghcnh._number(-9999) is None
    assert ghcnh._number("") is None
    assert ghcnh._number("54") == 54.0


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 10, 2, tzinfo=UTC), [2026]),
        (datetime(2025, 12, 31, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC), [2025, 2026]),
        (datetime(2025, 12, 31, tzinfo=UTC), datetime(2026, 1, 1, tzinfo=UTC), [2025]),
    ],
)
def test_years_touched_by_a_half_open_window(start, end, expected):
    assert list(ghcnh.years(start, end)) == expected


def test_rejects_malformed_station_ids():
    with pytest.raises(ValueError, match="station id"):
        ghcnh.station_year_key("../etc", 2026)


def test_run_loads_found_stations_and_records_missing_ones(raw_store, sink):
    s3 = FakeNoaaS3()
    manifest = extract_noaa(
        [STATION, "USW00099999"], START, END, s3=s3, raw_store=raw_store, sink=sink, now=lambda: NOW
    )
    assert manifest["status"] == "succeeded"
    assert manifest["stations_missing"] == ["USW00099999"]
    assert manifest["rows_appended"] == len(sink.appended) == manifest["rows_received"] > 0
    assert manifest["run_id"] == noaa_run_id(START, END, [STATION, "USW00099999"])
    assert raw_store.watermarks[("noaa-ghcnh", tuple(sorted([STATION, "USW00099999"])))] == END
    assert len(raw_store.manifests) == 1


def test_run_fails_loudly_when_no_station_has_data(raw_store, sink):
    with pytest.raises(NoStationDataError):
        extract_noaa(["USW00099999"], START, END, s3=FakeNoaaS3(), raw_store=raw_store, sink=sink)
    (manifest,) = raw_store.manifests.values()
    assert manifest["status"] == "failed" and sink.appended == []
