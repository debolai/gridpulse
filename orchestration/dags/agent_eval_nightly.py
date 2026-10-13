"""Nightly evaluation of the agent against the live semantic API, in two steps:

1. golden_set_eval: the planner must turn at least 90% of the golden questions into the expected
   metric request (the same gate as pull requests).
2. end_to_end_eval: the full graph answers every question as a user would: clarifying questions,
   follow-ups in one conversation, the number check. It records answer accuracy and number-check
   failures; below 90% the task fails (and alerts). It runs even when step 1 fails, so a bad
   night still leaves its scores.

Both store their scores in the agent database (table eval_runs) for trends.

On Kubernetes the agent runs on Bedrock only (it refuses API-key providers there), so this DAG
fails on k3d/EKS until Bedrock is unblocked (TODO #11); locally it uses the temporary provider.
"""

from datetime import datetime, timedelta

from _gridpulse import AGENT_IMAGE, EXTRACT_DEFAULTS, container_task
from airflow.sdk import DAG

with DAG(
    dag_id="agent_eval_nightly",
    description="Score the agent's planner and full answers on the golden question set",
    schedule="0 7 * * *",
    start_date=datetime(2026, 10, 1),
    catchup=False,
    max_active_runs=1,
    default_args={**EXTRACT_DEFAULTS, "retries": 1, "execution_timeout": timedelta(minutes=45)},
    tags=["gridpulse", "agent", "quality"],
) as dag:
    planner = container_task(
        task_id="golden_set_eval",
        component="agent",
        image=AGENT_IMAGE,
        entrypoint=["gridpulse-agent-eval"],
        arguments=[],
    )
    end_to_end = container_task(
        task_id="end_to_end_eval",
        component="agent",
        image=AGENT_IMAGE,
        entrypoint=["gridpulse-agent-eval"],
        arguments=["--e2e"],
        trigger_rule="all_done",
    )
    planner >> end_to_end
