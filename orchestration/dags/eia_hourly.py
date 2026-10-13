"""Hourly EIA extraction: region-data, fuel-type-data and interchange-data in parallel.

Each run re-reads the last 72 hours ending at its slot (revisions land in recent hours).
catchup=False: after downtime the extractor's `--start auto` reaches back to its watermark and
fills the whole gap in ONE run, instead of Airflow replaying every missed hour (two weeks down
would otherwise be ~336 runs, each re-pulling 72 hours). When all three routes have loaded, the
raw_eia asset is published, which triggers dbt_build. A route that still fails after its retries
holds back that hour's dbt run; the next hour's `--start auto` covers the gap.
"""

from datetime import datetime

from _gridpulse import EIA_ROUTES, EXTRACT_DEFAULTS, RAW_EIA, eia_extract
from airflow.sdk import DAG, task

with DAG(
    dag_id="eia_hourly",
    description="Extract the three EIA routes (72h lookback, gap-filling) into the raw lake",
    schedule="15 * * * *",
    start_date=datetime(2026, 10, 1),
    catchup=False,
    max_active_runs=1,
    default_args=EXTRACT_DEFAULTS,
    tags=["gridpulse", "ingestion", "eia"],
) as dag:

    @task(outlets=[RAW_EIA])
    def publish_raw_eia() -> None:
        """Marks new raw EIA data: dbt_build runs on this asset event."""

    extracts = [eia_extract(route, "auto") for route in EIA_ROUTES]
    extracts >> publish_raw_eia()
