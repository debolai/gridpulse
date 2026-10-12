import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "eia_region_data"


@pytest.fixture
def region_pages() -> list[dict]:
    """Real EIA responses: ERCO + PJM, 2026-10-01T00..T12, page size 40 (40 + 40 + 16 rows)."""
    return [json.loads(p.read_text()) for p in sorted(FIXTURES.glob("page_*.json"))]


@pytest.fixture
def region_meta() -> dict:
    return json.loads((FIXTURES / "meta.json").read_text())


class FakeRawStore:
    def __init__(self) -> None:
        self.pages: dict[str, bytes] = {}
        self.manifests: dict[str, dict] = {}

    page_key = staticmethod(
        lambda route, day, run_id, n: (
            f"eia/route={route}/ingest_date={day}/run_id={run_id}/page={n:04d}.json.gz"
        )
    )
    manifest_key = staticmethod(
        lambda route, day, run_id: (
            f"_manifests/route={route}/ingest_date={day}/run_id={run_id}.json"
        )
    )

    def put_page(self, key: str, raw: bytes) -> None:
        self.pages[key] = raw

    def put_manifest(self, key: str, manifest: dict) -> None:
        self.manifests[key] = dict(manifest)


class FakeSink:
    def __init__(self) -> None:
        self.appended: list[dict] = []
        self.calls = 0

    def append(self, route, records) -> int:
        self.calls += 1
        self.appended.extend(records)
        return len(records)


@pytest.fixture
def raw_store() -> FakeRawStore:
    return FakeRawStore()


@pytest.fixture
def sink() -> FakeSink:
    return FakeSink()
