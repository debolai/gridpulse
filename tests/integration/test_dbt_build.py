"""A3 check: the dbt project builds (models, data tests, unit tests) on the local Trino target,
and an incremental rerun with no new data changes nothing. Builds into `test_<id>_*` schemas
and drops them afterwards.

Needs the local lake (`make up-lake`) with some raw data loaded (`make extract-sample ...`).
"""

import os
import subprocess
import uuid
from pathlib import Path

import pytest
import trino

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]


def dbt(*args: str, prefix: str) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "DBT_PROJECT_DIR": "transform",
        "DBT_PROFILES_DIR": "transform",
        "GRIDPULSE_SCHEMA_PREFIX": prefix,
    }
    return subprocess.run(
        ["uv", "run", "--quiet", "dbt", *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def prefix():
    name = f"test_{uuid.uuid4().hex[:8]}"
    yield name
    result = dbt(
        "run-operation", "drop_prefixed_schemas", "--args", f"{{prefix: {name}}}", prefix=""
    )
    assert result.returncode == 0, result.stdout[-2000:]


def count(cursor, table: str) -> int:
    cursor.execute(f"SELECT count(*) FROM {table}")
    return cursor.fetchall()[0][0]


def test_build_then_incremental_noop(prefix):
    assert dbt("deps", prefix=prefix).returncode == 0
    first = dbt("build", prefix=prefix)
    assert first.returncode == 0, first.stdout[-4000:]

    cur = trino.dbapi.connect(host="localhost", port=8080, user="test", catalog="lake").cursor()
    fct = f"lake.{prefix}_marts.fct_grid_hourly"
    rows = count(cur, fct)
    assert rows > 0

    second = dbt("build", "--select", "int_grid__latest_values", "fct_grid_hourly", prefix=prefix)
    assert second.returncode == 0, second.stdout[-4000:]
    assert "MERGE (0 rows)" in second.stdout or "MERGE (-1 rows)" in second.stdout
    assert count(cur, fct) == rows
