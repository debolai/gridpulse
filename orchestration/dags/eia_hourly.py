"""Hourly EIA region-data extraction.

Each run re-reads the last 72 hours ending at its data interval (revisions land in recent
hours). catchup=False: after downtime the extractor's `--start auto` reaches back to its
watermark and fills the whole gap in ONE run, instead of Airflow replaying every missed hour
(two weeks down would otherwise be ~336 runs, each re-pulling 72 hours). Publishes the raw_eia
asset, which triggers dbt_build.
"""

from datetime import datetime

from _gridpulse import (
    DOCKER_TASK,
    EXTRACT_DEFAULTS,
    EXTRACTOR_ENV,
    INGESTION_IMAGE,
    RAW_EIA,
    RESPONDENTS,
)
from airflow.providers.docker.operators.docker import DockerOperator
from airflow.sdk import DAG

with DAG(
    dag_id="eia_hourly",
    description="Extract EIA region-data (72h lookback, gap-filling) into the raw lake",
    schedule="15 * * * *",
    start_date=datetime(2026, 10, 1),
    catchup=False,
    max_active_runs=1,
    default_args=EXTRACT_DEFAULTS,
    tags=["gridpulse", "ingestion", "eia"],
) as dag:
    DockerOperator(
        task_id="extract_region_data",
        image=INGESTION_IMAGE,
        command=[
            "eia",
            "--route",
            "region-data",
            "--start",
            "auto",
            # Anchored to the run's slot, not "now": a rerun pulls the same window. In Airflow 3,
            # run_after is the cron slot for scheduled runs and the trigger time for manual ones
            # (manual runs have no data interval at all).
            "--end",
            "{{ dag_run.run_after.strftime('%Y-%m-%dT%H') }}",
            "--lookback-hours",
            "72",
            "--respondents",
            RESPONDENTS,
        ],
        # The key comes from the AIRFLOW_VAR_EIA_API_KEY env var (never stored in Airflow's DB);
        # its name contains "api_key", so Airflow masks it in the UI and logs.
        environment={**EXTRACTOR_ENV, "EIA_API_KEY": "{{ var.value.eia_api_key }}"},
        pool="eia_api",
        # One extract of this route at a time: concurrent runs would race on the watermark and
        # on Iceberg commits (seen when a leftover retry overlapped a new run).
        max_active_tis_per_dag=1,
        outlets=[RAW_EIA],
        **DOCKER_TASK,
    )
