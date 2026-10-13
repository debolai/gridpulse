"""Where conversations live between messages (LangGraph checkpoints).

Postgres when GRIDPULSE_AGENT_CHECKPOINT_DSN is set: its own database on the shared instance
(blueprint: the same Postgres as Airflow's metadata, a separate database). Otherwise in memory,
which is fine for tests and a single local process but forgets everything on restart.
"""

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from gridpulse_agent.config import AgentSettings
from gridpulse_agent.graph import checkpoint_serializer


def checkpointer(settings: AgentSettings):
    if settings.checkpoint_dsn is None:
        return InMemorySaver(serde=checkpoint_serializer())
    pool = ConnectionPool(
        settings.checkpoint_dsn.get_secret_value(),
        max_size=4,
        # PostgresSaver's own requirements: autocommit, dict rows, no server-side prepares.
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        open=True,
    )
    saver = PostgresSaver(pool, serde=checkpoint_serializer())
    saver.setup()  # creates or migrates its tables; safe to run on every start
    return saver
