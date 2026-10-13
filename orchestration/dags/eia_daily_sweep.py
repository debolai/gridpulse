"""Daily 30-day re-pull of the three EIA routes to catch late revisions.

EIA keeps revising values for weeks (day-ahead forecasts get re-issued, late fills arrive). The
hourly DAG only looks back 72 hours, so this sweep re-reads the last 30 days once a day; staging
keeps every version and the revision audit (fct_data_revisions) records what changed.
"""

from datetime import datetime

from _gridpulse import EIA_ROUTES, EXTRACT_DEFAULTS, RAW_EIA, eia_extract
from airflow.sdk import DAG, task

SWEEP_START = "{{ (dag_run.run_after - macros.timedelta(days=30)).strftime('%Y-%m-%dT%H') }}"

with DAG(
    dag_id="eia_daily_sweep",
    description="Re-pull the last 30 days of the three EIA routes to catch late revisions",
    schedule="0 4 * * *",
    start_date=datetime(2026, 10, 1),
    catchup=False,
    max_active_runs=1,
    default_args=EXTRACT_DEFAULTS,
    tags=["gridpulse", "ingestion", "eia"],
) as dag:

    @task(outlets=[RAW_EIA])
    def publish_raw_eia() -> None:
        """Marks new raw EIA data: dbt_build runs on this asset event."""

    [eia_extract(route, SWEEP_START) for route in EIA_ROUTES] >> publish_raw_eia()
