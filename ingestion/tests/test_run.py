import gzip
import json
from datetime import UTC, datetime

import pytest

from gridpulse_ingestion.eia.client import Page
from gridpulse_ingestion.eia.routes import REGION_DATA
from gridpulse_ingestion.run import RecordValidationError, extract, run_id_for
from gridpulse_ingestion.storage import RawStore, raw_table_schema

START = datetime(2026, 10, 1, 0, tzinfo=UTC)
END = datetime(2026, 10, 1, 12, tzinfo=UTC)
NOW = datetime(2026, 10, 12, 17, 0, tzinfo=UTC)


class ReplayClient:
    def __init__(self, pages: list[dict]) -> None:
        self._pages = pages

    def fetch_window(self, route, start, end, facets=()):
        offset = 0
        for n, body in enumerate(self._pages, start=1):
            rows = body["response"]["data"]
            yield Page(
                n,
                offset,
                int(body["response"]["total"]),
                rows,
                json.dumps(body).encode(),
                body["apiVersion"],
            )
            offset += len(rows)


def run(pages, raw_store, sink, facets=("ERCO", "PJM")):
    return extract(
        REGION_DATA,
        START,
        END,
        client=ReplayClient(pages),
        raw_store=raw_store,
        sink=sink,
        facets=facets,
        now=lambda: NOW,
    )


def test_run_writes_pages_rows_and_manifest(region_pages, raw_store, sink):
    manifest = run(region_pages, raw_store, sink)

    assert manifest["status"] == "succeeded"
    assert manifest["rows_expected"] == manifest["rows_received"] == manifest["rows_appended"] == 96
    assert manifest["pages"] == 3
    assert sink.calls == 1  # one Iceberg commit per run keeps files few and large
    run_id = manifest["run_id"]
    assert sorted(raw_store.pages) == [
        f"eia/route=region-data/ingest_date=2026-10-12/run_id={run_id}/page={n:04d}.json.gz"
        for n in (1, 2, 3)
    ]
    assert list(raw_store.manifests) == [
        f"_manifests/route=region-data/ingest_date=2026-10-12/run_id={run_id}/"
        "attempt=20261012T170000000000Z.json"
    ]


def test_failed_attempt_manifest_survives_a_successful_retry(region_pages, raw_store, sink):
    broken = json.loads(json.dumps(region_pages))
    del broken[0]["response"]["data"][0]["respondent"]
    times = iter([NOW, NOW.replace(minute=5)])
    with pytest.raises(RecordValidationError):
        extract(
            REGION_DATA,
            START,
            END,
            client=ReplayClient(broken),
            raw_store=raw_store,
            sink=sink,
            now=lambda: next(times),
        )
    extract(
        REGION_DATA,
        START,
        END,
        client=ReplayClient(region_pages),
        raw_store=raw_store,
        sink=sink,
        now=lambda: next(times),
    )

    statuses = [m["status"] for _, m in sorted(raw_store.manifests.items())]
    assert statuses == ["failed", "succeeded"]


def test_records_match_the_raw_table_schema(region_pages, raw_store, sink):
    run(region_pages, raw_store, sink)
    names = {f.name for f in raw_table_schema(REGION_DATA).fields}
    assert all(set(r) == names for r in sink.appended)
    first = sink.appended[0]
    assert first["value"] == "75544"  # still a string in raw
    assert first["period_utc"] == START
    assert first["_ingested_at"] == NOW


def test_reruns_are_deterministic(region_pages, raw_store, sink):
    first = run(region_pages, raw_store, sink)
    hashes_first = [r["_record_hash"] for r in sink.appended]
    sink.appended.clear()
    second = run(region_pages, raw_store, sink)

    assert first["run_id"] == second["run_id"]
    assert [r["_record_hash"] for r in sink.appended] == hashes_first
    assert len(set(hashes_first)) == 96  # every row version is distinct


def test_run_id_depends_on_window_and_facets():
    base = run_id_for(REGION_DATA, START, END, ["PJM", "ERCO"])
    assert base == run_id_for(REGION_DATA, START, END, ["ERCO", "PJM"])  # facet order irrelevant
    assert base != run_id_for(REGION_DATA, START, END, ["PJM"])
    assert base != run_id_for(
        REGION_DATA, START, datetime(2026, 10, 1, 13, tzinfo=UTC), ["PJM", "ERCO"]
    )


def test_revised_value_gets_a_new_hash(region_pages, raw_store, sink):
    run(region_pages, raw_store, sink)
    original = sink.appended[0]["_record_hash"]
    revised = json.loads(json.dumps(region_pages))
    revised[0]["response"]["data"][0]["value"] = "75545"
    sink.appended.clear()
    run(revised, raw_store, sink)
    assert sink.appended[0]["_record_hash"] != original


def test_unknown_fields_go_to_overflow_and_manifest(region_pages, raw_store, sink):
    drifted = json.loads(json.dumps(region_pages))
    drifted[0]["response"]["data"][0]["new-field"] = "x"
    manifest = run(drifted, raw_store, sink)

    assert manifest["status"] == "succeeded"
    assert manifest["unknown_fields"] == ["new-field"]
    assert json.loads(sink.appended[0]["_extra"]) == {"new-field": "x"}


def test_bad_row_fails_batch_appends_nothing_and_records_failure(region_pages, raw_store, sink):
    broken = json.loads(json.dumps(region_pages))
    del broken[1]["response"]["data"][5]["respondent"]

    with pytest.raises(RecordValidationError):
        run(broken, raw_store, sink)

    assert sink.calls == 0
    (manifest,) = raw_store.manifests.values()
    assert manifest["status"] == "failed"
    assert "RecordValidationError" in manifest["error"]


def test_raw_store_gzip_is_deterministic():
    class S3:
        def __init__(self):
            self.bodies = []

        def put_object(self, **kwargs):
            self.bodies.append(kwargs["Body"])

    s3 = S3()
    store = RawStore(s3, "bucket")
    store.put_page("k", b'{"a": 1}')
    store.put_page("k", b'{"a": 1}')
    assert s3.bodies[0] == s3.bodies[1]
    assert gzip.decompress(s3.bodies[0]) == b'{"a": 1}'


def test_watermark_moves_forward_only_on_success(region_pages, raw_store, sink):
    run(region_pages, raw_store, sink)
    assert raw_store.get_watermark("region-data", ["ERCO", "PJM"]) == END
    broken = json.loads(json.dumps(region_pages))
    del broken[0]["response"]["data"][0]["respondent"]
    later_end = datetime(2026, 10, 2, 0, tzinfo=UTC)
    with pytest.raises(RecordValidationError):
        extract(
            REGION_DATA,
            START,
            later_end,
            client=ReplayClient(broken),
            raw_store=raw_store,
            sink=sink,
            facets=("ERCO", "PJM"),
            now=lambda: NOW,
        )
    assert raw_store.get_watermark("region-data", ["ERCO", "PJM"]) == END  # failure: unchanged


def test_auto_start_normal_run_rereads_the_lookback():
    from datetime import timedelta

    from gridpulse_ingestion.run import resolve_auto_start

    end = datetime(2026, 10, 12, 10, tzinfo=UTC)
    start, warning = resolve_auto_start(
        end, end - timedelta(hours=1), timedelta(hours=72), timedelta(days=30)
    )
    assert start == end - timedelta(hours=72) and warning is None


def test_auto_start_fills_a_gap_after_downtime():
    from datetime import timedelta

    from gridpulse_ingestion.run import resolve_auto_start

    end = datetime(2026, 10, 12, 10, tzinfo=UTC)
    watermark = end - timedelta(days=9)
    start, warning = resolve_auto_start(end, watermark, timedelta(hours=72), timedelta(days=30))
    assert start == watermark and warning is None


def test_auto_start_caps_long_gaps_and_warns():
    from datetime import timedelta

    from gridpulse_ingestion.run import resolve_auto_start

    end = datetime(2026, 10, 12, 10, tzinfo=UTC)
    start, warning = resolve_auto_start(
        end, end - timedelta(days=90), timedelta(hours=72), timedelta(days=30)
    )
    assert start == end - timedelta(days=30) and "Backfill" in warning
