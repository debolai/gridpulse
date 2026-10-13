"""Daily NOAA GHCNh weather for the stations in the dbt seed (ADR-0004).

`--start auto` re-reads the last 7 days (NOAA publishes with about a 1.5-day lag and fills in
late reports) and reaches back to the watermark after downtime. Publishes raw_noaa, which
triggers dbt_build. The public NOAA bucket is read anonymously, so no API pool is needed.
"""

from datetime import datetime

from _gridpulse import (
    EXTRACT_DEFAULTS,
    INGESTION_IMAGE,
    RAW_NOAA,
    RUN_HOUR,
    container_task,
    weather_stations,
)
from airflow.sdk import DAG

with DAG(
    dag_id="noaa_daily",
    description="Load NOAA GHCNh observations for the seed's weather stations",
    schedule="0 6 * * *",
    start_date=datetime(2026, 10, 1),
    catchup=False,
    max_active_runs=1,
    default_args=EXTRACT_DEFAULTS,
    tags=["gridpulse", "ingestion", "noaa"],
) as dag:
    container_task(
        task_id="load_noaa_ghcnh",
        component="extractor",
        image=INGESTION_IMAGE,
        arguments=[
            "noaa",
            "--stations",
            weather_stations(),
            "--start",
            "auto",
            "--end",
            RUN_HOUR,
        ],
        max_active_tis_per_dag=1,
        outlets=[RAW_NOAA],
    )
