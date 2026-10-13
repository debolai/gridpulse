"""B4: conversations survive a restart when checkpoints live in Postgres.

Needs the local Postgres (`make up-lake`). Uses a throwaway database, dropped afterwards.
"""

import uuid
from datetime import date

import psycopg
import pytest
from pydantic import SecretStr

from gridpulse_agent.config import AgentSettings
from gridpulse_agent.contract import MetricRequest, RouteDecision
from gridpulse_agent.graph import ask, build_graph
from gridpulse_agent.memory import checkpointer

pytestmark = pytest.mark.integration

ADMIN = "postgresql://gridpulse:gridpulse@localhost:5433/gridpulse"
CISO_PEAK = MetricRequest.model_validate(
    {
        "metrics": ["peak_demand"],
        "filters": [{"dimension": "balancing_authority", "values": ["CISO"]}],
        "start": "2026-09-01T00:00:00Z",
        "end": "2026-10-01T00:00:00Z",
    }
)
REGIONS = [
    {"code": c, "name": c, "region": "CAL", "region_name": "California"}
    for c in ("CISO", "BANC", "LDWP")
]


class Brain:
    def route(self, question, history=()):
        return RouteDecision(route="metric", reason="test")

    def plan(self, question, *args, **kwargs):
        return CISO_PEAK

    def answer(self, *args):
        return "CISO peaked at 46,213 MW."


class Semantic:
    def catalog(self):
        return [{"name": "peak_demand", "dimensions": ["balancing_authority"]}]

    def balancing_authorities(self):
        return [("CISO", "California ISO")]

    def saved_queries(self):
        return []

    def ba_regions(self):
        return REGIONS

    def query(self, request):
        return {"columns": ["peak_demand"], "rows": [[46213.0]], "sql": "select ...", "notes": []}

    def coverage(self, request):
        return [["CISO", 720, 720]]

    def latest_hour(self):
        return None


@pytest.fixture
def dsn():
    name = f"test_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(ADMIN, autocommit=True) as conn:
        conn.execute(f"CREATE DATABASE {name}")
    yield f"postgresql://gridpulse:gridpulse@localhost:5433/{name}"
    with psycopg.connect(ADMIN, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE {name} WITH (FORCE)")


def test_a_paused_conversation_resumes_after_a_restart(dsn):
    settings = AgentSettings(_env_file=None, checkpoint_dsn=SecretStr(dsn))
    first = build_graph(Brain(), Semantic(), settings, checkpointer(settings))
    asked = ask(first, "What was California's peak demand?", today=date(2026, 10, 12))
    assert asked["status"] == "needs_clarification"

    # A new process: new graph, new connection pool, same database.
    second = build_graph(Brain(), Semantic(), settings, checkpointer(settings))
    out = ask(second, "CISO only", thread_id=asked["thread_id"])
    assert out["status"] == "answered" and out["thread_id"] == asked["thread_id"]

    third = build_graph(Brain(), Semantic(), settings, checkpointer(settings))
    state = third.get_state({"configurable": {"thread_id": asked["thread_id"]}}).values
    assert [t["question"] for t in state["history"]] == [
        "What was California's peak demand? CISO only"
    ]
