"""dbt build, triggered by new raw data (asset-driven, not a guessed clock), then a semantic
API cache refresh so answers reflect the new data."""

import json
import logging
import urllib.request
from datetime import datetime

from _gridpulse import DBT_DEFAULTS, DOCKER_TASK, RAW_EIA, SEMANTIC_API_URL, TRANSFORM_IMAGE
from airflow.providers.docker.operators.docker import DockerOperator
from airflow.sdk import DAG, task

log = logging.getLogger(__name__)

with DAG(
    dag_id="dbt_build",
    description="Build and test all dbt models when raw EIA data lands, then refresh the cache",
    schedule=[RAW_EIA],
    start_date=datetime(2026, 10, 1),
    catchup=False,
    max_active_runs=1,
    default_args=DBT_DEFAULTS,
    tags=["gridpulse", "dbt"],
) as dag:
    dbt_build = DockerOperator(
        task_id="dbt_build",
        image=TRANSFORM_IMAGE,
        command=["build"],
        environment={"DBT_TARGET": "local", "TRINO_HOST": "trino", "TRINO_PORT": "8080"},
        **DOCKER_TASK,
    )

    @task(retries=1)
    def refresh_semantic_cache() -> str:
        """Best effort: if the API isn't running (e.g. only the `orch` profile is up), skip."""
        req = urllib.request.Request(f"{SEMANTIC_API_URL}/cache/refresh", method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                version = json.load(resp)["data_version"]
        except OSError as exc:
            log.warning("semantic API not reachable at %s (%s); skipping", SEMANTIC_API_URL, exc)
            return "skipped"
        log.info("semantic cache refreshed: %s", version)
        return version

    dbt_build >> refresh_semantic_cache()
