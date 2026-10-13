import json
from datetime import date, datetime
from pathlib import Path

import pytest

from gridpulse_agent.config import AgentSettings
from gridpulse_agent.contract import MetricRequest, RouteDecision
from gridpulse_agent.semantic_client import SemanticAPIError

FIXTURES = Path(__file__).parent / "fixtures"
TODAY = date(2026, 10, 12)


@pytest.fixture
def catalog() -> list[dict]:
    """The real agent catalog, snapshotted from the semantic API."""
    return json.loads((FIXTURES / "catalog.json").read_text())


@pytest.fixture
def settings() -> AgentSettings:
    return AgentSettings(_env_file=None, provider="bedrock")


def req(**overrides) -> MetricRequest:
    body = {"metrics": ["demand"], "start": "2026-09-01T00:00:00Z", "end": "2026-10-01T00:00:00Z"}
    return MetricRequest.model_validate({**body, **overrides})


class ScriptedBrain:
    """Plays back queued plans and answers; records what the graph asked for."""

    def __init__(self, route="metric", plans=(), answers=(), definition="defined"):
        self._route = route
        self.plans = list(plans)
        self.answers = list(answers)
        self.definition = definition
        self.plan_calls: list[dict] = []
        self.answer_calls: list[list[str]] = []

    def route(self, question, history=()):
        return RouteDecision(route=self._route, reason="scripted")

    def plan(self, question, catalog, bas, today, errors, previous, saved_queries=(), history=()):
        self.plan_calls.append(
            {
                "question": question,
                "history": list(history),
                "errors": list(errors),
                "previous": previous,
                "saved_queries": list(saved_queries),
            }
        )
        return self.plans.pop(0)

    def answer(self, question, request, result, catalog, bad):
        self.answer_calls.append(list(bad))
        return self.answers.pop(0)

    def define(self, question, catalog):
        return self.definition


# Coverage and freshness the fake reports unless a test says otherwise: complete data, loaded
# up to the pinned "today", so windows in September 2026 are older than the revision window.
FULL_COVERAGE = [["PJM", 720, 720]]
LATEST_HOUR = datetime(2026, 10, 12, 9)


class FakeSemantic:
    def __init__(
        self,
        catalog,
        results=(),
        reject_first: str | None = None,
        coverage=FULL_COVERAGE,
        latest_hour=LATEST_HOUR,
    ):
        self._catalog = catalog
        self.results = list(results)
        self.reject_first = reject_first
        self.queries: list[MetricRequest] = []
        self._coverage = coverage
        self._latest = latest_hour
        self.coverage_requests: list[MetricRequest] = []

    def coverage(self, request):
        self.coverage_requests.append(request)
        if isinstance(self._coverage, Exception):
            raise self._coverage
        return self._coverage

    def latest_hour(self):
        return self._latest

    def ba_regions(self):
        return json.loads((FIXTURES / "ba_regions.json").read_text())

    def catalog(self):
        return self._catalog

    def saved_queries(self):
        return json.loads((FIXTURES / "saved_queries.json").read_text())

    def balancing_authorities(self):
        return json.loads((FIXTURES / "bas.json").read_text())

    def query(self, request):
        self.queries.append(request)
        if self.reject_first:
            message, self.reject_first = self.reject_first, None
            raise SemanticAPIError(message)
        return self.results.pop(0)
