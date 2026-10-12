"""HTTP API over the semantic layer: the only way the agent (and dashboards) get numbers.

GET  /health     liveness + which engine/target and data version
GET  /metrics    the metric catalog (?agent_only=true for the agent's allow-list)
POST /compile    MetricRequest -> SQL (no execution)
POST /query      MetricRequest -> rows, the SQL that produced them, cache info
"""

import os
from functools import lru_cache
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from gridpulse_semantic.engine import SemanticEngine
from gridpulse_semantic.requests import MetricRequest

app = FastAPI(title="GridPulse semantic API", version="0.1.0")


@lru_cache(maxsize=1)
def engine() -> SemanticEngine:
    project = Path(os.environ.get("DBT_PROJECT_DIR", "transform")).resolve()
    profiles = Path(os.environ.get("DBT_PROFILES_DIR", str(project))).resolve()
    return SemanticEngine(project, profiles)


class CompileResponse(BaseModel):
    sql: str


class QueryResponse(BaseModel):
    columns: list[str]
    rows: list[list]
    row_count: int
    sql: str
    cached: bool
    duration_ms: int
    data_version: str


def _known(req: MetricRequest) -> None:
    """Reject unknown metrics/dimensions with a clear message before MetricFlow sees them."""
    catalog = {m["name"]: m for m in engine().catalog()}
    unknown = [m for m in req.metrics if m not in catalog]
    if unknown:
        raise HTTPException(422, f"unknown metric(s): {unknown}; see GET /metrics")
    allowed = set.intersection(*(set(catalog[m]["dimensions"]) for m in req.metrics))
    allowed |= engine().entity_names | {
        f"metric_time__{g}" for g in ("hour", "day", "week", "month", "quarter", "year")
    }
    names = list(req.group_by) + [f.dimension for f in req.filters]
    bad = [n for n in names if n not in allowed]
    if bad:
        raise HTTPException(422, f"dimension(s) not available for these metrics: {bad}")


@app.get("/health")
def health() -> dict:
    e = engine()
    return {"status": "ok", "target": e.target, "data_version": e.data_version()}


@app.get("/metrics")
def metrics(agent_only: bool = False) -> list[dict]:
    return engine().catalog(agent_only=agent_only)


@app.post("/compile", response_model=CompileResponse)
def compile_sql(req: MetricRequest) -> CompileResponse:
    _known(req)
    try:
        return CompileResponse(sql=engine().compile(req))
    except Exception as exc:  # MetricFlow raises many types; surface a 422 with its message
        raise HTTPException(422, f"{type(exc).__name__}: {exc}") from exc


@app.post("/query", response_model=QueryResponse)
def query(req: MetricRequest) -> QueryResponse:
    _known(req)
    try:
        r = engine().query(req)
    except Exception as exc:
        raise HTTPException(422, f"{type(exc).__name__}: {exc}") from exc
    return QueryResponse(row_count=len(r.rows), **r.__dict__)


def main() -> None:
    uvicorn.run(
        app, host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8090"))
    )
