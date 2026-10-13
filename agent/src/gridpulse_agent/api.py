"""HTTP front door for the assistant.

GET  /health
POST /ask   {"question": "...", "thread_id": optional} -> answer, status, metric request, SQL,
            rows, thread_id. status "needs_clarification" means the answer is a question: send
            the user's reply as the next question with the same thread_id.
POST /ask/stream   same body; Server-Sent Events: {"type": "step", "node": ...} per graph
            step, then {"type": "result", ...} (as /ask), or {"type": "error", ...} (as a 503).
"""

import hmac
import json
import logging
import os
from collections.abc import Iterator
from functools import lru_cache

import httpx
import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from gridpulse_agent.brain import LLMBrain
from gridpulse_agent.config import AgentSettings
from gridpulse_agent.graph import ask, ask_stream, build_graph
from gridpulse_agent.memory import checkpointer
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
    brain, semantic = LLMBrain.from_settings(s), SemanticClient(s.semantic_api_url)
    return build_graph(brain, semantic, s, checkpointer(s))


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


def unavailable(exc: Exception) -> tuple[dict, int | None] | None:
    """(body, retry-after seconds) for an outage the user should hear about plainly: the
    semantic API unreachable or the model provider failing. None for anything else (a bug)."""
    if isinstance(exc, httpx.HTTPError):
        try:
            url = str(exc.request.url)
        except RuntimeError:  # httpx raises when the error carries no request
            url = ""
        if not url.startswith(settings().semantic_api_url):
            return None
        log.warning("semantic API unavailable: %r", exc)
        body = {
            "status": "metrics_unavailable",
            "message": "The metrics API is not reachable right now. Try again shortly.",
            "detail": type(exc).__name__,
        }
        return body, 30
    problem = classify(exc)
    if problem is None:
        return None
    log.warning("model provider unavailable (%s): %s", problem.reason, problem.provider_error)
    body = {
        "status": f"model_{problem.reason}",
        "message": problem.message,
        "detail": problem.provider_error,
    }
    return body, problem.retry_after_s


@app.post("/ask", dependencies=[Depends(authorize)])
def ask_endpoint(body: Question):
    try:
        return ask(graph(), body.question, thread_id=body.thread_id)
    except Exception as exc:
        outage = unavailable(exc)
        if outage is None:
            raise
        content, retry_after_s = outage
        headers = {"Retry-After": str(retry_after_s)} if retry_after_s else None
        return JSONResponse(status_code=503, content=content, headers=headers)


@app.post("/ask/stream", dependencies=[Depends(authorize)])
def ask_stream_endpoint(body: Question) -> StreamingResponse:
    def events() -> Iterator[str]:
        try:
            for event in ask_stream(graph(), body.question, thread_id=body.thread_id):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as exc:
            outage = unavailable(exc)
            if outage is None:
                log.exception("ask/stream failed")
                outage = (
                    {"status": "error", "message": "Something went wrong.", "detail": ""},
                    None,
                )
            content, retry_after_s = outage
            event = {"type": "error", **content, "retry_after_s": retry_after_s}
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


def main() -> None:
    uvicorn.run(
        app, host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8091"))
    )
