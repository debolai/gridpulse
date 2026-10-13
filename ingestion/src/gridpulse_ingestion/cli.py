"""Command line entry point.

gridpulse-extract eia --route region-data --start ... --end ...
gridpulse-extract noaa --stations USW00094846,USW00013739 --start ... --end ...
"""

import argparse
import json
import logging
import sys
from datetime import UTC, datetime, timedelta

from gridpulse_ingestion.config import Settings
from gridpulse_ingestion.eia.client import EIAClient
from gridpulse_ingestion.eia.routes import ROUTES
from gridpulse_ingestion.ratelimit import TokenBucket
from gridpulse_ingestion.run import extract, extract_noaa, resolve_auto_start
from gridpulse_ingestion.storage import IcebergSink, RawStore, run_record


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
    eia.add_argument(
        "--start",
        required=True,
        help="inclusive, UTC; or 'auto': last --lookback-hours, reaching back to the last "
        "successful load after downtime (at most --max-gap-days)",
    )
    eia.add_argument("--end", type=_utc_hour, required=True, help="exclusive, UTC")
    eia.add_argument(
        "--respondents",
        default="",
        help="comma-separated BA codes (default: all balancing authorities)",
    )
    eia.add_argument("--lookback-hours", type=int, default=72)
    eia.add_argument("--max-gap-days", type=int, default=30)
    noaa = sub.add_parser("noaa", help="load NOAA GHCNh station observations for [start, end)")
    noaa.add_argument("--stations", required=True, help="comma-separated GHCNh station ids")
    noaa.add_argument(
        "--start", required=True, help="inclusive, UTC; or 'auto': the last --lookback-days"
    )
    noaa.add_argument("--end", type=_utc_hour, required=True, help="exclusive, UTC")
    noaa.add_argument("--lookback-days", type=int, default=7)
    noaa.add_argument("--max-gap-days", type=int, default=60)
    sub.add_parser(
        "manifests",
        help="append every run manifest in the raw bucket to raw.ingestion_runs "
        "(staging keeps one row per attempt, so rerunning is safe)",
    )
    return parser.parse_args(argv)


def run_noaa(args: argparse.Namespace, settings: Settings) -> dict:
    import boto3
    from botocore import UNSIGNED
    from botocore.config import Config

    stations = [s.strip().upper() for s in args.stations.split(",") if s.strip()]
    raw_store = RawStore.from_settings(settings)
    if args.start == "auto":
        start, warning = resolve_auto_start(
            args.end,
            raw_store.get_watermark("noaa-ghcnh", stations),
            timedelta(days=args.lookback_days),
            timedelta(days=args.max_gap_days),
        )
        if warning:
            logging.getLogger("gridpulse.extract").warning(warning)
    else:
        start = _utc_hour(args.start)
    # The public NOAA bucket on real AWS, anonymously: never the local S3 endpoint or our keys.
    noaa_s3 = boto3.client("s3", region_name="us-east-1", config=Config(signature_version=UNSIGNED))
    return extract_noaa(
        stations,
        start,
        args.end,
        s3=noaa_s3,
        raw_store=raw_store,
        sink=IcebergSink.from_settings(settings),
    )


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # httpx logs full request URLs at INFO, and EIA URLs carry the API key.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    args = parse_args(argv)
    settings = Settings()
    if args.source == "manifests":
        now = datetime.now(UTC)
        records = [run_record(m, now) for m in RawStore.from_settings(settings).iter_manifests()]
        appended = IcebergSink.from_settings(settings).append_runs(records)
        print(json.dumps({"manifests_appended": appended}))
        return 0
    if args.source == "noaa":
        json.dump(run_noaa(args, settings), sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
        return 0
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
    raw_store = RawStore.from_settings(settings)
    if args.start == "auto":
        start, warning = resolve_auto_start(
            args.end,
            raw_store.get_watermark(route.name, facets),
            timedelta(hours=args.lookback_hours),
            timedelta(days=args.max_gap_days),
        )
        if warning:
            logging.getLogger("gridpulse.extract").warning(warning)
    else:
        start = _utc_hour(args.start)
    manifest = extract(
        route,
        start,
        args.end,
        client=client,
        raw_store=raw_store,
        sink=IcebergSink.from_settings(settings),
        facets=facets,
    )
    json.dump(manifest, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
