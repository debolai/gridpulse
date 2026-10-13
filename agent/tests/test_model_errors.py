from types import SimpleNamespace

import anthropic
import httpx
import openai
import pytest
from botocore.exceptions import ClientError, EndpointConnectionError
from fastapi.testclient import TestClient

from gridpulse_agent import api
from gridpulse_agent.config import AgentSettings
from gridpulse_agent.model_errors import classify

REQ = httpx.Request("POST", "https://api.example.com/v1/x")


def bedrock(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "..."}}, "Converse")


def status(cls, code: int):
    return cls("...", response=httpx.Response(code, request=REQ), body=None)


@pytest.mark.parametrize(
    ("exc", "reason"),
    [
        (bedrock("ThrottlingException"), "throttled"),
        (bedrock("AccessDeniedException"), "access_denied"),
        (bedrock("ModelNotReadyException"), "unreachable"),
        (EndpointConnectionError(endpoint_url="https://bedrock"), "unreachable"),
        (status(openai.RateLimitError, 429), "throttled"),
        (status(openai.AuthenticationError, 401), "access_denied"),
        (status(openai.InternalServerError, 500), "unreachable"),
        (openai.APIConnectionError(request=REQ), "unreachable"),
        (status(anthropic.RateLimitError, 429), "throttled"),
        (status(anthropic.PermissionDeniedError, 403), "access_denied"),
    ],
)
def test_provider_failures_are_classified(exc, reason):
    problem = classify(exc)
    assert problem is not None and problem.reason == reason
    assert type(exc).__name__ in problem.provider_error


@pytest.mark.parametrize(
    "exc",
    [
        ValueError("bug"),
        bedrock("ValidationException"),  # a bad request is our bug, not an outage
        status(openai.BadRequestError, 400),
        httpx.ConnectError("refused", request=REQ),  # httpx is left to the API (URL check)
    ],
)
def test_other_errors_are_not_masked(exc):
    assert classify(exc) is None


class Raising:
    def __init__(self, exc):
        self.exc = exc

    def get_state(self, _config):
        return SimpleNamespace(interrupts=())  # no clarifying question pending

    def invoke(self, _state, _config=None):
        raise self.exc


@pytest.fixture
def client(monkeypatch):
    settings = AgentSettings(_env_file=None, semantic_api_url="http://semantic:8090")
    monkeypatch.setattr(api, "settings", lambda: settings)

    def make(exc):
        monkeypatch.setattr(api, "graph", lambda: Raising(exc))
        return TestClient(api.app, raise_server_exceptions=False)

    return make


def ask(client):
    return client.post("/ask", json={"question": "PJM demand in July 2026?"})


def test_throttled_model_returns_503_with_retry_after(client):
    resp = ask(client(bedrock("ThrottlingException")))
    assert resp.status_code == 503
    assert resp.headers["Retry-After"] == "60"
    body = resp.json()
    assert body["status"] == "model_throttled"
    assert "rate-limited" in body["message"]
    assert body["detail"] == "ClientError: ThrottlingException"


def test_unreachable_semantic_api_returns_503(client):
    exc = httpx.ConnectError("refused", request=httpx.Request("POST", "http://semantic:8090/query"))
    resp = ask(client(exc))
    assert resp.status_code == 503
    assert resp.json()["status"] == "metrics_unavailable"


def test_other_httpx_and_unknown_errors_stay_500(client):
    assert ask(client(httpx.ConnectError("refused", request=REQ))).status_code == 500
    assert ask(client(ValueError("bug"))).status_code == 500
