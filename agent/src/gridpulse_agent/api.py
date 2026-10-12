"""HTTP front door for the assistant.

GET  /health
POST /ask   {"question": "..."} -> answer, status, metric request, SQL, rows
"""

import hmac
import os
from functools import lru_cache

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from gridpulse_agent.brain import LLMBrain
from gridpulse_agent.config import AgentSettings
from gridpulse_agent.graph import ask, build_graph
from gridpulse_agent.semantic_client import SemanticClient

app = FastAPI(title="GridPulse assistant", version="0.1.0")


@lru_cache(maxsize=1)
def settings() -> AgentSettings:
    return AgentSettings()


@lru_cache(maxsize=1)
def graph():
    s = settings()
    return build_graph(LLMBrain.from_settings(s), SemanticClient(s.semantic_api_url), s)


def authorize(authorization: str | None = Header(default=None)) -> None:
    token = settings().api_token
    if token is None:
        return
    expected = f"Bearer {token.get_secret_value()}"
    if not authorization or not hmac.compare_digest(authorization, expected):
        raise HTTPException(401, "missing or wrong bearer token")


class Question(BaseModel):
    question: str = Field(min_length=3, max_length=500)


@app.get("/health")
def health() -> dict:
    s = settings()
    router, planner = s.models()
    return {
        "status": "ok",
        "provider": s.provider,
        "router_model": router,
        "planner_model": planner,
    }


@app.post("/ask", dependencies=[Depends(authorize)])
def ask_endpoint(body: Question) -> dict:
    return ask(graph(), body.question)


def main() -> None:
    uvicorn.run(
        app, host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8091"))
    )
