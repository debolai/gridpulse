from pathlib import Path

import pytest
from eia_fixtures import recorded_meta, recorded_pages

from gridpulse_ingestion.storage import RawStore

FIXTURES = Path(__file__).parent / "fixtures" / "eia_region_data"


@pytest.fixture
def region_pages() -> list[dict]:
    """region-data: 40 + 40 + 16 rows."""
    return recorded_pages("region-data")


@pytest.fixture
def region_meta() -> dict:
    return recorded_meta("region-data")


class FakeRawStore:
    def __init__(self) -> None:
        self.pages: dict[str, bytes] = {}
        self.manifests: dict[str, dict] = {}

    page_key = staticmethod(
        lambda route, day, run_id, n: (
            f"eia/route={route}/ingest_date={day}/run_id={run_id}/page={n:04d}.json.gz"
        )
    )
    manifest_key = staticmethod(RawStore.manifest_key)

    def put_page(self, key: str, raw: bytes) -> None:
        self.pages[key] = raw

    def put_manifest(self, key: str, manifest: dict) -> None:
        self.manifests[key] = dict(manifest)

    watermarks: dict

    def get_watermark(self, route, facets):
        return getattr(self, "watermarks", {}).get((route, tuple(sorted(facets))))

    def advance_watermark(self, route, facets, window_end):
        self.watermarks = getattr(self, "watermarks", {})
        key = (route, tuple(sorted(facets)))
        if key not in self.watermarks or self.watermarks[key] < window_end:
            self.watermarks[key] = window_end


class FakeSink:
    def __init__(self) -> None:
        self.appended: list[dict] = []
        self.calls = 0

    def append(self, route, records) -> int:
        self.calls += 1
        self.appended.extend(records)
        return len(records)

    def append_runs(self, records) -> int:
        self.runs = getattr(self, "runs", []) + list(records)
        return len(records)

    def append_noaa(self, records) -> int:
        return self.append("noaa-ghcnh", records)


@pytest.fixture
def raw_store() -> FakeRawStore:
    return FakeRawStore()


@pytest.fixture
def sink() -> FakeSink:
    return FakeSink()
