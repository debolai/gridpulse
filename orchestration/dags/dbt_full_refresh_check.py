"""Monthly proof that incremental models are correct: rebuild everything from raw into a scratch
prefix (frc_<run>), compare each mart with production (macro `compare_full_refresh`), then drop
the scratch schemas whatever happened. Runs after the daily sweep, so production is settled.
"""

from datetime import datetime, timedelta

from _gridpulse import DBT_DEFAULTS, TRANSFORM_IMAGE, container_task
from airflow.exceptions import AirflowFailException
from airflow.sdk import DAG, task

PREFIX = "frc_{{ dag_run.run_after.strftime('%Y%m%d%H%M') }}"

with DAG(
    dag_id="dbt_full_refresh_check",
    description="Rebuild the marts from scratch and prove they equal the incremental ones",
    schedule="0 5 1 * *",
    start_date=datetime(2026, 10, 1),
    catchup=False,
    max_active_runs=1,
    default_args={**DBT_DEFAULTS, "execution_timeout": timedelta(hours=3)},
    tags=["gridpulse", "dbt", "quality"],
) as dag:
    rebuild = container_task(
        task_id="full_rebuild",
        component="dbt",
        image=TRANSFORM_IMAGE,
        arguments=["build", "--full-refresh", "--exclude", "test_type:unit"],
        env={"GRIDPULSE_SCHEMA_PREFIX": PREFIX},
    )
    compare = container_task(
        task_id="compare_with_production",
        component="dbt",
        image=TRANSFORM_IMAGE,
        arguments=["run-operation", "compare_full_refresh", "--args", f"{{prefix: {PREFIX}}}"],
    )
    drop = container_task(
        task_id="drop_scratch_schemas",
        component="dbt",
        image=TRANSFORM_IMAGE,
        arguments=["run-operation", "drop_prefixed_schemas", "--args", f"{{prefix: {PREFIX}}}"],
        trigger_rule="all_done",
    )

    @task(trigger_rule="one_failed")
    def fail_run() -> None:
        """The cleanup always runs and succeeds, and Airflow judges a run by its last tasks, so
        without this a failed comparison would leave the run green (and alert nobody)."""
        raise AirflowFailException("the full-refresh check failed; see the tasks above")

    rebuild >> compare >> drop
    [rebuild, compare, drop] >> fail_run()
