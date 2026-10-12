"""Command line entry point: `gridpulse-extract eia --route region-data --start ... --end ...`."""

import argparse
import json
import logging
import sys
from datetime import UTC, datetime

from gridpulse_ingestion.config import Settings
from gridpulse_ingestion.eia.client import EIAClient
from gridpulse_ingestion.eia.routes import ROUTES
from gridpulse_ingestion.ratelimit import TokenBucket
from gridpulse_ingestion.run import extract
from gridpulse_ingestion.storage import IcebergSink, RawStore


def _utc_hour(value: str) -> datetime:
    """Accepts 2026-10-01T00 or 2026-10-01 (midnight UTC)."""
    for fmt in ("%Y-%m-%dT%H", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD or YYYY-MM-DDTHH (UTC), got {value!r}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="gridpulse-extract")
    sub = parser.add_subparsers(dest="source", required=True)
    eia = sub.add_parser("eia", help="extract one EIA route for a UTC window [start, end)")
    eia.add_argument("--route", choices=sorted(ROUTES), required=True)
    eia.add_argument("--start", type=_utc_hour, required=True, help="inclusive, UTC")
    eia.add_argument("--end", type=_utc_hour, required=True, help="exclusive, UTC")
    eia.add_argument(
        "--respondents",
        default="",
        help="comma-separated BA codes (default: all balancing authorities)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # httpx logs full request URLs at INFO, and EIA URLs carry the API key.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    args = parse_args(argv)
    settings = Settings()
    route = ROUTES[args.route]
    facets = [r.strip().upper() for r in args.respondents.split(",") if r.strip()]
    client = EIAClient(
        settings.eia_api_key.get_secret_value(),
        base_url=settings.eia_base_url,
        page_size=settings.eia_page_size,
        limiter=TokenBucket(settings.eia_requests_per_second),
        max_attempts=settings.eia_max_attempts,
        timeout_seconds=settings.eia_timeout_seconds,
    )
    manifest = extract(
        route,
        args.start,
        args.end,
        client=client,
        raw_store=RawStore.from_settings(settings),
        sink=IcebergSink.from_settings(settings),
        facets=facets,
    )
    json.dump(manifest, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
