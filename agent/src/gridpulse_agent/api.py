"""HTTP front door for the assistant.

GET  /health
POST /ask   {"question": "...", "thread_id": optional} -> answer, status, metric request, SQL,
            rows, thread_id. status "needs_clarification" means the answer is a question: send
            the user's reply as the next question with the same thread_id.
"""

import hmac
import logging
import os
from functools import lru_cache

import httpx
import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from gridpulse_agent.brain import LLMBrain
from gridpulse_agent.config import AgentSettings
from gridpulse_agent.graph import ask, build_graph
from gridpulse_agent.model_errors import classify
from gridpulse_agent.semantic_client import SemanticClient

app = FastAPI(title="GridPulse assistant", version="0.1.0")
log = logging.getLogger(__name__)


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
    question: str = Field(min_length=2, max_length=500)  # 2: a reply can be a BA code ("PJM")
    thread_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,64}$")


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


def unavailable(status: str, message: str, detail: str, retry_after_s: int | None) -> JSONResponse:
    """503 with a message the UI can show as is; never a raw stack trace."""
    headers = {"Retry-After": str(retry_after_s)} if retry_after_s else None
    body = {"status": status, "message": message, "detail": detail}
    return JSONResponse(status_code=503, content=body, headers=headers)


@app.post("/ask", dependencies=[Depends(authorize)])
def ask_endpoint(body: Question):
    try:
        return ask(graph(), body.question, thread_id=body.thread_id)
    except httpx.HTTPError as exc:
        try:
            url = str(exc.request.url)
        except RuntimeError:  # httpx raises when the error carries no request
            url = ""
        if not url.startswith(settings().semantic_api_url):
            raise
        log.warning("semantic API unavailable: %r", exc)
        return unavailable(
            "metrics_unavailable",
            "The metrics API is not reachable right now. Try again shortly.",
            type(exc).__name__,
            30,
        )
    except Exception as exc:
        problem = classify(exc)
        if problem is None:
            raise
        log.warning("model provider unavailable (%s): %s", problem.reason, problem.provider_error)
        return unavailable(
            f"model_{problem.reason}",
            problem.message,
            problem.provider_error,
            problem.retry_after_s,
        )


def main() -> None:
    uvicorn.run(
        app, host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8091"))
    )
