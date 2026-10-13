"""HTTP client for the semantic API: the agent's only source of numbers."""

import time
from datetime import datetime

import httpx

from gridpulse_agent.contract import MetricRequest
from gridpulse_agent.inspection import coverage_request


class SemanticAPIError(RuntimeError):
    """The semantic API rejected a request (unknown name, invalid query).

    The message is safe to show the planner.
    """


class SemanticClient:
    def __init__(self, base_url: str, http: httpx.Client | None = None, ttl_seconds: int = 600):
        self._http = http or httpx.Client(base_url=base_url, timeout=120)
        self._ttl = ttl_seconds
        self._cache: dict[str, tuple[float, object]] = {}

    def _cached(self, key: str, loader):
        hit = self._cache.get(key)
        if hit and time.monotonic() - hit[0] < self._ttl:
            return hit[1]
        value = loader()
        self._cache[key] = (time.monotonic(), value)
        return value

    def catalog(self) -> list[dict]:
        """Metrics the agent may use (tagged agent: true), with their dimensions."""

        def load():
            resp = self._http.get("/metrics", params={"agent_only": True})
            resp.raise_for_status()
            return resp.json()

        return self._cached("catalog", load)

    def saved_queries(self) -> list[dict]:
        """Common questions as request templates (tagged agent), for the planner to start from."""

        def load():
            resp = self._http.get("/saved-queries", params={"agent_only": True})
            resp.raise_for_status()
            return resp.json()

        return self._cached("saved", load)

    def balancing_authorities(self) -> list[tuple[str, str]]:
        """(code, name) for every BA with data, so the planner can map names to codes."""

        def load():
            body = {
                "metrics": ["demand"],
                "group_by": ["balancing_authority", "balancing_authority__ba_name"],
                "limit": 500,
            }
            resp = self._http.post("/query", json=body)
            resp.raise_for_status()
            return sorted((row[0], row[1]) for row in resp.json()["rows"])

        return self._cached("bas", load)

    def coverage(self, request: MetricRequest) -> list[list]:
        """[ba_code, valid demand hours, expected hours] for the request's BAs and window."""
        return self.query(coverage_request(request))["rows"]

    def latest_hour(self) -> datetime | None:
        """The latest hour with demand anywhere (where the coverage spine ends)."""

        def load():
            body = {
                "metrics": ["expected_hours"],
                "group_by": ["metric_time__hour"],
                "order_by": ["-metric_time__hour"],
                "limit": 1,
            }
            resp = self._http.post("/query", json=body)
            resp.raise_for_status()
            rows = resp.json()["rows"]
            return datetime.fromisoformat(rows[0][0]) if rows else None

        return self._cached("latest", load)

    def query(self, request: MetricRequest) -> dict:
        resp = self._http.post("/query", json=request.model_dump(mode="json"))
        if resp.status_code == 422:
            raise SemanticAPIError(resp.json().get("detail", resp.text))
        resp.raise_for_status()
        return resp.json()
