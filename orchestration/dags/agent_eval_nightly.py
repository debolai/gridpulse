"""Nightly golden-set evaluation of the agent against the live semantic API: the planner must
turn at least 90% of the questions into the expected metric request, or the task fails (and
alerts). Today it scores the planner; B4 adds full-graph answers and stores the scores.

On Kubernetes the agent runs on Bedrock only (it refuses API-key providers there), so this DAG
fails on k3d/EKS until Bedrock is unblocked (TODO #11); locally it uses the temporary provider.
"""

from datetime import datetime, timedelta

from _gridpulse import AGENT_IMAGE, EXTRACT_DEFAULTS, container_task
from airflow.sdk import DAG

with DAG(
    dag_id="agent_eval_nightly",
    description="Score the agent's planner on the golden question set",
    schedule="0 7 * * *",
    start_date=datetime(2026, 10, 1),
    catchup=False,
    max_active_runs=1,
    default_args={**EXTRACT_DEFAULTS, "retries": 1, "execution_timeout": timedelta(minutes=30)},
    tags=["gridpulse", "agent", "quality"],
) as dag:
    container_task(
        task_id="golden_set_eval",
        component="agent",
        image=AGENT_IMAGE,
        entrypoint=["gridpulse-agent-eval"],
        arguments=[],
    )
