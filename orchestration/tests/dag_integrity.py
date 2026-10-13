"""DAG integrity checks, run inside the Airflow image (`make dag-check`): every DAG imports,
has no cycles, and every task sets retries and a timeout; EIA calls go through the pool.
Run once per runtime (GRIDPULSE_TASK_RUNTIME=docker|kubernetes): both build different operators.
"""

import os
import sys
from pathlib import Path

from airflow.dag_processing.dagbag import DagBag

# Airflow puts the DAGs folder on sys.path when it parses DAGs; do the same here.
sys.path.insert(0, "/opt/airflow/dags")

bag = DagBag(dag_folder=Path("/opt/airflow/dags"), known_pools={"default_pool", "eia_api"})
problems = [f"import error in {path}: {err}" for path, err in bag.import_errors.items()]
expected = {
    "eia_hourly",
    "eia_daily_sweep",
    "noaa_daily",
    "dbt_build",
    "lake_maintenance",
    "dbt_full_refresh_check",
    "agent_eval_nightly",
}
missing = expected - set(bag.dag_ids)
if missing:
    problems.append(f"missing DAGs: {sorted(missing)}")
for dag_id, dag in bag.dags.items():
    if dag.catchup:
        problems.append(f"{dag_id}: catchup must be False (gaps are filled by --start auto)")
    for t in dag.tasks:
        if not t.execution_timeout:
            problems.append(f"{dag_id}.{t.task_id}: no execution_timeout")
        if t.retries is None or t.retries < 1:
            problems.append(f"{dag_id}.{t.task_id}: no retries")
        if t.task_id.startswith("extract_") and t.pool != "eia_api":
            problems.append(f"{dag_id}.{t.task_id}: EIA tasks must use the eia_api pool")
if "dbt_build" in bag.dags and len(bag.dags["dbt_build"].tasks) < 20:
    problems.append("dbt_build: Cosmos rendered too few tasks (is the manifest baked in?)")
for p in problems:
    print("FAIL", p)
runtime = os.environ.get("GRIDPULSE_TASK_RUNTIME", "docker")
n_tasks = sum(len(d.tasks) for d in bag.dags.values())
print(
    f"[{runtime}] checked {len(bag.dags)} DAGs, {n_tasks} tasks: "
    f"{'OK' if not problems else f'{len(problems)} problem(s)'}"
)
sys.exit(1 if problems else 0)
