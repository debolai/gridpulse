"""A2 check: the extractor container loads real EIA data, and rerunning a window adds no new
distinct rows. Uses its own `test_<id>` namespace and deletes everything it wrote afterwards.

Needs the local lake (`make up-lake`) and EIA_API_KEY in .env.
"""

import json
import os
import subprocess
import uuid
from pathlib import Path

import boto3
import pytest
import trino

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ["docker", "compose", "-f", str(ROOT / "local/compose.yaml")]
WINDOW = ["--start", "2026-09-01T00", "--end", "2026-09-01T06", "--respondents", "ERCO,PJM"]


def _has_key() -> bool:
    env = ROOT / ".env"
    return "EIA_API_KEY" in os.environ or (env.exists() and "EIA_API_KEY=" in env.read_text())


@pytest.fixture
def namespace():
    if not _has_key():
        pytest.skip("EIA_API_KEY not set")
    name = f"test_{uuid.uuid4().hex[:8]}"
    yield name
    cur = trino.dbapi.connect(host="localhost", port=8080, user="test", catalog="lake").cursor()
    cur.execute(f"SHOW TABLES FROM lake.{name}")
    for (table,) in cur.fetchall():
        cur.execute(f"DROP TABLE lake.{name}.{table}")
        cur.fetchall()
    cur.execute(f"DROP SCHEMA IF EXISTS lake.{name}")
    cur.fetchall()


def run_extractor(namespace: str) -> dict:
    result = subprocess.run(
        [
            *COMPOSE,
            "run",
            "--rm",
            "-e",
            f"GRIDPULSE_RAW_NAMESPACE={namespace}",
            "extractor",
            "eia",
            "--route",
            "region-data",
            *WINDOW,
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr[-3000:]
    return json.loads(result.stdout[result.stdout.index("{") :])


@pytest.fixture
def raw_cleanup():
    s3 = boto3.client(
        "s3",
        endpoint_url="http://localhost:8333",
        region_name="local-01",
        aws_access_key_id="gridpulse-local",
        aws_secret_access_key="gridpulse-local-secret",
    )
    run_ids: list[str] = []
    yield run_ids
    for run_id in run_ids:
        for obj in s3.list_objects_v2(Bucket="gridpulse-local-raw").get("Contents", []):
            if f"run_id={run_id}" in obj["Key"]:
                s3.delete_object(Bucket="gridpulse-local-raw", Key=obj["Key"])


def test_rerun_adds_no_new_distinct_rows(namespace, raw_cleanup):
    first = run_extractor(namespace)
    raw_cleanup.append(first["run_id"])
    second = run_extractor(namespace)

    assert first["status"] == second["status"] == "succeeded"
    assert first["rows_received"] == first["rows_expected"] > 0
    assert first["run_id"] == second["run_id"]

    cur = trino.dbapi.connect(host="localhost", port=8080, user="test", catalog="lake").cursor()
    cur.execute(
        f"SELECT count(*), count(DISTINCT _record_hash) FROM lake.{namespace}.eia_region_data"
    )
    total, distinct = cur.fetchall()[0]
    assert total == 2 * first["rows_received"]  # raw is append-only: both loads kept
    assert distinct == first["rows_received"]  # ...but nothing new and distinct
