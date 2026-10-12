"""Shared settings for GridPulse DAGs. Everything environment-specific comes from env vars, so
the same DAG files run locally (DockerOperator) and, in phase B2, on EKS."""

import os
from datetime import timedelta

from airflow.sdk import Asset

RAW_EIA = Asset("gridpulse://raw/eia_region_data")

INGESTION_IMAGE = os.environ.get("GRIDPULSE_INGESTION_IMAGE", "gridpulse/ingestion:local")
TRANSFORM_IMAGE = os.environ.get("GRIDPULSE_TRANSFORM_IMAGE", "gridpulse/transform:local")
DOCKER_NETWORK = os.environ.get("GRIDPULSE_DOCKER_NETWORK", "gridpulse_default")
# Local runs load the sample BAs only; empty = every balancing authority (AWS).
RESPONDENTS = os.environ.get("GRIDPULSE_RESPONDENTS", "CISO,ERCO,ISNE,MISO,NYIS,PJM")
SEMANTIC_API_URL = os.environ.get("GRIDPULSE_SEMANTIC_API_URL", "http://semantic-api:8090")

# Extractor env inside the compose network (same values as the compose `extractor` service).
EXTRACTOR_ENV = {
    "GRIDPULSE_RAW_BUCKET": "gridpulse-local-raw",
    "GRIDPULSE_S3_ENDPOINT": "http://seaweedfs:8333",
    "GRIDPULSE_S3_ACCESS_KEY": "gridpulse-local",
    "GRIDPULSE_S3_SECRET_KEY": "gridpulse-local-secret",
    "GRIDPULSE_S3_REGION": "local-01",
    "GRIDPULSE_CATALOG_TYPE": "rest",
    "GRIDPULSE_CATALOG_URI": "http://lakekeeper:8181/catalog",
    "GRIDPULSE_CATALOG_WAREHOUSE": "gridpulse",
}

EXTRACT_DEFAULTS = {
    "owner": "gridpulse",
    "retries": 3,
    "retry_delay": timedelta(minutes=2),
    "retry_exponential_backoff": True,
    "execution_timeout": timedelta(minutes=20),
}
DBT_DEFAULTS = {**EXTRACT_DEFAULTS, "retries": 2, "execution_timeout": timedelta(minutes=30)}

DOCKER_TASK = {
    "network_mode": DOCKER_NETWORK,
    "auto_remove": "success",
    "mount_tmp_dir": False,
    "docker_url": "unix://var/run/docker.sock",
}
