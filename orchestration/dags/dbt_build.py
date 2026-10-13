"""dbt build through Cosmos, triggered by new raw data (asset-driven, not a guessed clock), then a
semantic API cache refresh so answers reflect the new data.

Cosmos renders each dbt node as its own task from the manifest baked into the Airflow image:
`dbt build --select <model>` runs a model and its data tests together, so a failed model
retries alone and the graph shows dbt lineage. Sources with a freshness rule get a
`dbt source freshness` task upstream of their models. Unit tests run in CI, not on the schedule.
"""

import json
import logging
import urllib.request
from datetime import datetime

from _gridpulse import (
    DBT_DEFAULTS,
    DBT_MANIFEST,
    RAW_EIA,
    RAW_NOAA,
    SEMANTIC_API_URL,
    cosmos_execution,
)
from airflow.sdk import DAG, task
from cosmos import DbtTaskGroup, ProjectConfig, RenderConfig
from cosmos.constants import LoadMode, SourceRenderingBehavior, TestBehavior

log = logging.getLogger(__name__)

execution_config, operator_args = cosmos_execution()

with DAG(
    dag_id="dbt_build",
    description="Build and test the dbt models when raw EIA or NOAA data lands, then refresh",
    schedule=(RAW_EIA | RAW_NOAA),
    start_date=datetime(2026, 10, 1),
    catchup=False,
    max_active_runs=1,
    # Trino and Athena both handle a few concurrent statements comfortably; more just queues.
    max_active_tasks=4,
    default_args=DBT_DEFAULTS,
    tags=["gridpulse", "dbt"],
) as dag:
    dbt = DbtTaskGroup(
        group_id="dbt",
        project_config=ProjectConfig(manifest_path=DBT_MANIFEST, project_name="gridpulse"),
        execution_config=execution_config,
        render_config=RenderConfig(
            load_method=LoadMode.DBT_MANIFEST,
            test_behavior=TestBehavior.BUILD,
            source_rendering_behavior=SourceRenderingBehavior.WITH_TESTS_OR_FRESHNESS,
        ),
        operator_args={
            **operator_args,
            # Passed to dbt itself (Cosmos's own selector doesn't know test_type).
            "exclude": "test_type:unit",
            # A stale fct_grid_hourly fails the run (and alerts) here; dev builds only warn.
            "vars": {"freshness_severity": "error"},
        },
    )

    @task(retries=1)
    def refresh_semantic_cache() -> str:
        """Best effort: if the semantic API isn't running, skip rather than fail the build."""
        req = urllib.request.Request(f"{SEMANTIC_API_URL}/cache/refresh", method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                version = json.load(resp)["data_version"]
        except OSError as exc:
            log.warning("semantic API not reachable at %s (%s); skipping", SEMANTIC_API_URL, exc)
            return "skipped"
        log.info("semantic cache refreshed: %s", version)
        return version

    dbt >> refresh_semantic_cache()
