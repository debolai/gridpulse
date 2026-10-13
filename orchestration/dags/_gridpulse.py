"""Shared settings for GridPulse DAGs. Everything environment-specific comes from env vars, so
the same DAG files run on Docker Compose (DockerOperator) and on Kubernetes (k3d, EKS) through
KubernetesPodOperator.

GRIDPULSE_TASK_RUNTIME picks the operator:
  docker      task containers are siblings on the compose network; their env is set here.
  kubernetes  task pods take their env from the ConfigMap `gridpulse-<component>` and the
              Secret of the same name (both optional), installed with the Airflow Helm values,
              so the endpoints, catalog and credentials live with the deployment, not the DAGs.
"""

import csv
import json
import logging
import os
import urllib.request
from datetime import timedelta
from pathlib import Path

from airflow.sdk import Asset

RUNTIME = os.environ.get("GRIDPULSE_TASK_RUNTIME", "docker")
if RUNTIME not in ("docker", "kubernetes"):
    raise ValueError(f"GRIDPULSE_TASK_RUNTIME must be docker or kubernetes, got {RUNTIME!r}")

RAW_EIA = Asset("gridpulse://raw/eia")
RAW_NOAA = Asset("gridpulse://raw/noaa")

INGESTION_IMAGE = os.environ.get("GRIDPULSE_INGESTION_IMAGE", "gridpulse/ingestion:local")
TRANSFORM_IMAGE = os.environ.get("GRIDPULSE_TRANSFORM_IMAGE", "gridpulse/transform:local")
AGENT_IMAGE = os.environ.get("GRIDPULSE_AGENT_IMAGE", "gridpulse/agent:local")
DOCKER_NETWORK = os.environ.get("GRIDPULSE_DOCKER_NETWORK", "gridpulse_default")
K8S_NAMESPACE = os.environ.get("GRIDPULSE_TASK_NAMESPACE", "airflow")
# Local runs load the sample BAs only; empty = every balancing authority (AWS).
RESPONDENTS = os.environ.get("GRIDPULSE_RESPONDENTS", "CISO,ERCO,ISNE,MISO,NYIS,PJM")
SEMANTIC_API_URL = os.environ.get("GRIDPULSE_SEMANTIC_API_URL", "http://host.docker.internal:8090")
EIA_ROUTES = ("region-data", "fuel-type-data", "interchange-data")

# The dbt project's parsed manifest, baked into the Airflow image from the transform image (so
# the graph Cosmos renders matches the dbt code that runs) and the weather station seed (so the
# NOAA DAG and dbt agree on which stations exist).
DBT_MANIFEST = Path(os.environ.get("GRIDPULSE_DBT_MANIFEST", "/opt/airflow/dbt/manifest.json"))
STATIONS_SEED = Path(
    os.environ.get("GRIDPULSE_STATIONS_SEED", "/opt/airflow/dbt/ba_weather_stations.csv")
)


def weather_stations() -> str:
    """Comma-separated GHCNh station ids from the dbt seed (the single list of stations)."""
    with STATIONS_SEED.open(newline="") as f:
        return ",".join(sorted({row["station_id"] for row in csv.DictReader(f)}))


# Docker runtime only: task env inside the compose network (same values as the compose
# `extractor` service and the dbt `local` target).
DOCKER_ENV = {
    "extractor": {
        "GRIDPULSE_RAW_BUCKET": "gridpulse-local-raw",
        "GRIDPULSE_S3_ENDPOINT": "http://seaweedfs:8333",
        "GRIDPULSE_S3_ACCESS_KEY": "gridpulse-local",
        "GRIDPULSE_S3_SECRET_KEY": "gridpulse-local-secret",
        "GRIDPULSE_S3_REGION": "local-01",
        "GRIDPULSE_CATALOG_TYPE": "rest",
        "GRIDPULSE_CATALOG_URI": "http://lakekeeper:8181/catalog",
        "GRIDPULSE_CATALOG_WAREHOUSE": "gridpulse",
        # From the AIRFLOW_VAR_EIA_API_KEY env var (never stored in Airflow's DB); the name
        # contains "api_key", so Airflow masks it in the UI and logs.
        "EIA_API_KEY": "{{ var.value.eia_api_key }}",
    },
    "dbt": {"DBT_TARGET": "local", "TRINO_HOST": "trino", "TRINO_PORT": "8080"},
    "agent": {
        "GRIDPULSE_AGENT_SEMANTIC_API_URL": SEMANTIC_API_URL,
        # Temporary (ADR-0003): locally the provider and key come from .env (OpenAI for now).
        "GRIDPULSE_AGENT_PROVIDER": "{{ var.value.get('agent_provider', 'bedrock') }}",
        "GRIDPULSE_AGENT_OPENAI_API_KEY": "{{ var.value.get('openai_api_key', '') }}",
        # Eval scores (table eval_runs) go to the agent database on the compose Postgres
        # (local dummy credentials, as in compose.yaml).
        "GRIDPULSE_AGENT_CHECKPOINT_DSN": "postgresql://gridpulse:gridpulse@postgres:5432/agent",
    },
}

log = logging.getLogger(__name__)


def alert_on_failure(context) -> None:
    """Post a task's final failure (after its retries) to SLACK_WEBHOOK_URL, a Slack
    incoming webhook (any endpoint accepting {"text": ...} works). Without a URL the alert is
    only logged. Never raises: a broken webhook must not mask the task's own error."""
    ti = context["ti"]
    # First line only: pod failures append the whole pod spec.
    reason = (str(context.get("exception") or "").strip().splitlines() or [""])[0][:300]
    text = (
        f"GridPulse: {ti.dag_id}.{ti.task_id} failed (run {context.get('run_id')}, "
        f"try {ti.try_number}): {reason}"
    )
    log_url = getattr(ti, "log_url", None)
    if log_url:
        text += f"\nLogs: {log_url}"
    url = os.environ.get("SLACK_WEBHOOK_URL", "")
    if not url:
        log.warning("ALERT (no SLACK_WEBHOOK_URL set): %s", text)
        return
    req = urllib.request.Request(
        url,
        data=json.dumps({"text": text}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            log.info("alert sent (HTTP %s)", resp.status)
    except OSError as exc:
        log.error("alert webhook failed (%s); alert was: %s", exc, text)


EXTRACT_DEFAULTS = {
    "owner": "gridpulse",
    "on_failure_callback": alert_on_failure,
    "retries": 3,
    "retry_delay": timedelta(minutes=2),
    "retry_exponential_backoff": True,
    "execution_timeout": timedelta(minutes=20),
}
DBT_DEFAULTS = {**EXTRACT_DEFAULTS, "retries": 2, "execution_timeout": timedelta(minutes=30)}

_DOCKER_TASK = {
    "network_mode": DOCKER_NETWORK,
    "auto_remove": "success",
    "mount_tmp_dir": False,
    "docker_url": "unix://var/run/docker.sock",
    # Reach services running on the host (the semantic API during local development).
    "extra_hosts": {"host.docker.internal": "host-gateway"},
}


def _k8s_env_from(component: str) -> list:
    from kubernetes.client import models as k8s

    name = f"gridpulse-{component}"
    return [
        k8s.V1EnvFromSource(config_map_ref=k8s.V1ConfigMapEnvSource(name=name, optional=True)),
        k8s.V1EnvFromSource(secret_ref=k8s.V1SecretEnvSource(name=name, optional=True)),
    ]


# Task pod sizes (requests = limits for memory, so a heavy backfill can't starve the node).
K8S_MEMORY = {"extractor": "1Gi", "dbt": "1Gi", "agent": "512Mi"}


def _k8s_task(component: str) -> dict:
    from kubernetes.client import models as k8s

    memory = K8S_MEMORY[component]
    return {
        "namespace": K8S_NAMESPACE,
        "env_from": _k8s_env_from(component),
        "container_resources": k8s.V1ResourceRequirements(
            requests={"cpu": "100m", "memory": memory}, limits={"memory": memory}
        ),
        "service_account_name": f"gridpulse-{component}",
        "get_logs": True,
        "on_finish_action": "delete_succeeded_pod",
        "labels": {"app.kubernetes.io/part-of": "gridpulse", "gridpulse/component": component},
    }


def container_task(
    *,
    task_id: str,
    component: str,
    image: str,
    arguments: list[str],
    env: dict[str, str] | None = None,
    entrypoint: list[str] | None = None,
    **kwargs,
):
    """One task in its own container: `entrypoint` (default: the image's) runs with `arguments`.
    `env` adds task-specific variables on top of the component's environment."""
    if RUNTIME == "kubernetes":
        from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator

        return KubernetesPodOperator(
            task_id=task_id,
            name=task_id.replace("_", "-"),
            image=image,
            cmds=entrypoint,
            arguments=arguments,
            env_vars=env,
            **_k8s_task(component),
            **kwargs,
        )
    from airflow.providers.docker.operators.docker import DockerOperator

    return DockerOperator(
        task_id=task_id,
        image=image,
        entrypoint=entrypoint,
        command=arguments,
        environment={**DOCKER_ENV[component], **(env or {})},
        **_DOCKER_TASK,
        **kwargs,
    )


def cosmos_execution():
    """Cosmos execution mode and operator args for dbt tasks on the current runtime."""
    from cosmos import ExecutionConfig
    from cosmos.constants import ExecutionMode

    if RUNTIME == "kubernetes":
        # cmds=["dbt"] matches the image ENTRYPOINT, so Cosmos passes only the dbt arguments.
        args = {"image": TRANSFORM_IMAGE, "cmds": ["dbt"], **_k8s_task("dbt")}
        mode = ExecutionMode.KUBERNETES
    else:
        # Cosmos sends the full command including "dbt"; the image ENTRYPOINT is also dbt.
        args = {
            "image": TRANSFORM_IMAGE,
            "entrypoint": ["/usr/bin/env"],
            "environment": DOCKER_ENV["dbt"],
            **_DOCKER_TASK,
        }
        mode = ExecutionMode.DOCKER
    return ExecutionConfig(execution_mode=mode, dbt_project_path="/app/transform"), args


# Airflow 3: run_after is the cron slot for scheduled runs and the trigger time for manual ones
# (manual runs have no data interval at all). Windows anchor on it, never on "now", so a rerun
# pulls the same hours.
RUN_HOUR = "{{ dag_run.run_after.strftime('%Y-%m-%dT%H') }}"


def eia_extract(route: str, start: str, *, lookback_hours: int = 72):
    """Extract one EIA route for [start, RUN_HOUR). start may be 'auto' (gap-filling)."""
    return container_task(
        task_id=f"extract_{route.replace('-', '_')}",
        component="extractor",
        image=INGESTION_IMAGE,
        arguments=[
            "eia",
            "--route",
            route,
            "--start",
            start,
            "--end",
            RUN_HOUR,
            "--lookback-hours",
            str(lookback_hours),
            "--respondents",
            RESPONDENTS,
        ],
        pool="eia_api",
        # One extract of a route per DAG at a time: concurrent runs race on Iceberg commits.
        max_active_tis_per_dag=1,
    )
