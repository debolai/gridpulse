"""Weekly Iceberg maintenance: compaction, snapshot expiry (30 days kept for time travel) and
orphan-file cleanup on every raw source and dbt table. The engine-specific statements live in
the dbt macro `lake_maintenance` (Trino `ALTER TABLE ... EXECUTE`, Athena `OPTIMIZE`/`VACUUM`).
A commit that races an extract fails one side, and that side retries.
"""

from datetime import datetime, timedelta

from _gridpulse import DBT_DEFAULTS, TRANSFORM_IMAGE, container_task
from airflow.sdk import DAG

with DAG(
    dag_id="lake_maintenance",
    description="Compact Iceberg tables and expire old snapshots (weekly)",
    schedule="0 3 * * 0",
    start_date=datetime(2026, 10, 1),
    catchup=False,
    max_active_runs=1,
    default_args={**DBT_DEFAULTS, "execution_timeout": timedelta(hours=2)},
    tags=["gridpulse", "maintenance"],
) as dag:
    container_task(
        task_id="iceberg_maintenance",
        component="dbt",
        image=TRANSFORM_IMAGE,
        arguments=["run-operation", "lake_maintenance"],
    )
