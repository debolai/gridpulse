"""Re-record the EIA fixtures from the live API (needs EIA_API_KEY in .env).

Records each route for two BAs over 12 hours with a small page size, so tests exercise real
multi-page responses. Re-record when the API changes shape:

    uv run python ingestion/tests/fixtures/record_eia.py [route ...]   # default: all routes
"""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from gridpulse_ingestion.config import Settings
from gridpulse_ingestion.eia.client import EIAClient
from gridpulse_ingestion.eia.routes import ROUTES, Route

HERE = Path(__file__).parent
START = datetime(2026, 10, 1, 0, tzinfo=UTC)
END = datetime(2026, 10, 1, 12, tzinfo=UTC)
FACETS = ("ERCO", "PJM")
PAGE_SIZE = 40


def record(client: EIAClient, key: str, route: Route) -> None:
    out = HERE / ("eia_" + route.name.replace("-", "_"))
    out.mkdir(exist_ok=True)
    pages = list(client.fetch_window(route, START, END, FACETS))
    for page in pages:
        text = page.raw.decode()
        assert key not in text, "API key found in response; refusing to write fixture"
        body = json.loads(text)
        (out / f"page_{page.number:04d}.json").write_text(json.dumps(body, indent=1) + "\n")
    meta = {
        "start": START.isoformat(),
        "end": END.isoformat(),
        "facets": FACETS,
        "page_size": PAGE_SIZE,
        "pages": len(pages),
        "total": pages[-1].total,
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=1) + "\n")
    print(route.name, json.dumps(meta))


def main() -> None:
    key = Settings().eia_api_key.get_secret_value()
    client = EIAClient(key, page_size=PAGE_SIZE)
    for name in sys.argv[1:] or sorted(ROUTES):
        record(client, key, ROUTES[name])


if __name__ == "__main__":
    main()
