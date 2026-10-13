import pytest
from pydantic import ValidationError

from gridpulse_agent.brain import chat_model
from gridpulse_agent.config import AgentSettings


def test_openai_defaults_and_client():
    settings = AgentSettings(_env_file=None, provider="openai", openai_api_key="sk-test")
    router, planner = settings.models()
    assert (router, planner) == ("gpt-6-luna", "gpt-6.1-sol")
    model = chat_model(settings, planner)
    assert type(model).__name__ == "ChatOpenAI"
    assert model.model_name == "gpt-6.1-sol"
    assert "sk-test" not in repr(settings)  # the key never shows up in logs or errors


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
def test_api_key_providers_refuse_to_run_in_kubernetes(provider, monkeypatch):
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.0.0.1")
    with pytest.raises(ValidationError, match="local only"):
        AgentSettings(_env_file=None, provider=provider)


def test_bedrock_runs_in_kubernetes(monkeypatch):
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.0.0.1")
    assert AgentSettings(_env_file=None, provider="bedrock").provider == "bedrock"
