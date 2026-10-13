"""Agent settings (env prefix GRIDPULSE_AGENT_). The model provider is a one-line switch."""

import os
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Per-provider defaults: a small fast model routes, a larger one plans and answers.
DEFAULT_MODELS = {
    "bedrock": ("us.anthropic.claude-haiku-4-5-20251001-v1:0", "us.anthropic.claude-sonnet-4-6"),
    "anthropic": ("claude-haiku-4-5", "claude-sonnet-4-6"),
    "ollama": ("qwen3:8b", "qwen3:8b"),
    # Temporary, local only, until Bedrock quotas are lifted (ADR-0003, TODO #11).
    "openai": ("gpt-6-luna", "gpt-6.1-sol"),
}

# Providers that authenticate with an API key. The blueprint keeps API keys out of the cloud
# (Bedrock uses the pod's IAM role), so these refuse to start inside Kubernetes.
API_KEY_PROVIDERS = {"anthropic", "openai"}


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GRIDPULSE_AGENT_", env_file=".env", extra="ignore"
    )

    provider: Literal["bedrock", "anthropic", "ollama", "openai"] = "bedrock"
    router_model: str | None = None
    planner_model: str | None = None
    aws_region: str = "us-east-1"
    anthropic_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    ollama_url: str = "http://localhost:11434"

    semantic_api_url: str = "http://localhost:8090"
    max_plan_attempts: int = 3  # first plan + two retries after validation errors
    max_window_days: int = 400
    max_rows: int = 1000
    api_token: SecretStr | None = None  # demo bearer token for POST /ask; unset = open locally

    @model_validator(mode="after")
    def _api_keys_stay_local(self) -> "AgentSettings":
        if self.provider in API_KEY_PROVIDERS and os.environ.get("KUBERNETES_SERVICE_HOST"):
            raise ValueError(
                f"provider {self.provider!r} uses an API key and is local only; "
                "deployed agents use bedrock (ADR-0003)"
            )
        return self

    def models(self) -> tuple[str, str]:
        router, planner = DEFAULT_MODELS[self.provider]
        return self.router_model or router, self.planner_model or planner
