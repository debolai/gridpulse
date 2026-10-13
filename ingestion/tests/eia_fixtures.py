"""Recorded EIA responses (see fixtures/record_eia.py), shared by the ingestion tests."""

import json
from pathlib import Path

FIXTURE_ROOT = Path(__file__).parent / "fixtures"


def recorded_pages(route_name: str) -> list[dict]:
    """Real EIA responses for a route: ERCO + PJM, 2026-10-01T00..T12, page size 40."""
    folder = FIXTURE_ROOT / ("eia_" + route_name.replace("-", "_"))
    return [json.loads(p.read_text()) for p in sorted(folder.glob("page_*.json"))]


def recorded_meta(route_name: str) -> dict:
    folder = FIXTURE_ROOT / ("eia_" + route_name.replace("-", "_"))
    return json.loads((folder / "meta.json").read_text())
