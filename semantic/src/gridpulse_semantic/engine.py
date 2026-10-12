"""MetricFlow, wrapped: catalog, compile and query over the dbt project's semantic manifest."""

import hashlib
import json
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from dbt_metricflow.cli.cli_configuration import CLIConfiguration
from metricflow.engine.metricflow_engine import MetricFlowQueryRequest

from gridpulse_semantic.requests import MetricRequest, render_where


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[list]
    sql: str
    cached: bool
    duration_ms: int
    data_version: str


def _json_cell(value):
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


@dataclass
class _Cache:
    """Small LRU of query results. Keys include the data version, so a new dbt run (new data)
    makes every old entry unreachable."""

    max_entries: int = 256
    _items: OrderedDict = field(default_factory=OrderedDict)

    def get(self, key: str):
        if key in self._items:
            self._items.move_to_end(key)
            return self._items[key]
        return None

    def put(self, key: str, value) -> None:
        self._items[key] = value
        self._items.move_to_end(key)
        while len(self._items) > self.max_entries:
            self._items.popitem(last=False)


class SemanticEngine:
    def __init__(self, project_dir: Path, profiles_dir: Path) -> None:
        self._project_dir = project_dir
        config = CLIConfiguration()
        config.setup(
            dbt_profiles_path=profiles_dir,
            dbt_project_path=project_dir,
            configure_file_logging=False,
        )
        self._mf = config.mf
        self._lock = threading.Lock()  # MetricFlow's engine and dbt adapter aren't thread-safe
        self._cache = _Cache()
        self.target = os.environ.get("DBT_TARGET", "local")
        metrics = self._mf.list_metrics(include_dimensions=True)
        self.entity_names = {
            link.element_name for m in metrics for d in m.dimensions for link in d.entity_links
        }
        self._catalog = [self._describe(m) for m in metrics]

    @staticmethod
    def _describe(metric) -> dict:
        meta = dict(getattr(metric.config, "meta", None) or {}) if metric.config else {}
        return {
            "name": metric.name,
            "label": metric.label,
            "description": (metric.description or "").strip(),
            "type": metric.type.value,
            "agent": bool(meta.get("agent", False)),
            "unit": meta.get("unit"),
            "additive": meta.get("additive"),
            "synonyms": meta.get("synonyms", []),
            "dimensions": sorted({d.dunder_name for d in metric.dimensions}),
        }

    def catalog(self, agent_only: bool = False) -> list[dict]:
        return [m for m in self._catalog if m["agent"] or not agent_only]

    def data_version(self) -> str:
        """The dbt run that last built the marts; changes whenever new data lands."""
        run_results = self._project_dir / "target" / "run_results.json"
        try:
            meta = json.loads(run_results.read_text())["metadata"]
            return meta.get("invocation_id") or meta.get("generated_at", "unknown")
        except (OSError, KeyError, json.JSONDecodeError):
            return "unknown"

    def _request(self, req: MetricRequest) -> MetricFlowQueryRequest:
        return MetricFlowQueryRequest.create(
            metric_names=req.metrics,
            group_by_names=req.group_by or None,
            where_constraints=render_where(req, self.entity_names) or None,
            order_by_names=req.order_by or None,
            limit=req.limit,
        )

    def compile(self, req: MetricRequest) -> str:
        with self._lock:
            return self._mf.explain(self._request(req)).sql_statement.sql

    def query(self, req: MetricRequest) -> QueryResult:
        started = time.monotonic()
        sql = self.compile(req)
        version = self.data_version()
        key = hashlib.sha256(f"{self.target}|{version}|{sql}".encode()).hexdigest()
        if (hit := self._cache.get(key)) is not None:
            return QueryResult(**{**hit.__dict__, "cached": True, "duration_ms": 0})
        with self._lock:
            table = self._mf.query(self._request(req)).result_df
        result = QueryResult(
            columns=list(table.column_names),
            rows=[[_json_cell(c) for c in row] for row in table.rows],
            sql=sql,
            cached=False,
            duration_ms=int((time.monotonic() - started) * 1000),
            data_version=version,
        )
        self._cache.put(key, result)
        return result
