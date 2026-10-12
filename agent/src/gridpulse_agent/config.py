"""Agent settings (env prefix GRIDPULSE_AGENT_). The model provider is a one-line switch."""

from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Per-provider defaults: a small fast model routes, a larger one plans and answers.
DEFAULT_MODELS = {
    "bedrock": ("us.anthropic.claude-haiku-4-5-20251001-v1:0", "us.anthropic.claude-sonnet-4-6"),
    "anthropic": ("claude-haiku-4-5", "claude-sonnet-4-6"),
    "ollama": ("qwen3:8b", "qwen3:8b"),
}


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GRIDPULSE_AGENT_", env_file=".env", extra="ignore"
    )

    provider: Literal["bedrock", "anthropic", "ollama"] = "bedrock"
    router_model: str | None = None
    planner_model: str | None = None
    aws_region: str = "us-east-1"
    anthropic_api_key: SecretStr | None = None
    ollama_url: str = "http://localhost:11434"

    semantic_api_url: str = "http://localhost:8090"
    max_plan_attempts: int = 3  # first plan + two retries after validation errors
    max_window_days: int = 400
    max_rows: int = 1000
    api_token: SecretStr | None = None  # demo bearer token for POST /ask; unset = open locally

    def models(self) -> tuple[str, str]:
        router, planner = DEFAULT_MODELS[self.provider]
        return self.router_model or router, self.planner_model or planner
