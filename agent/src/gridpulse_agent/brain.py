"""The three model calls the graph makes (route, plan, answer, plus definitions), behind one
interface so tests can script them and the provider is a setting."""

import json
from datetime import date
from typing import Protocol

from langchain_core.language_models import BaseChatModel

from gridpulse_agent import prompts
from gridpulse_agent.config import AgentSettings
from gridpulse_agent.contract import MetricRequest, PlannedRequest, RouteDecision


class Brain(Protocol):
    def route(self, question: str, history: list[dict] = ()) -> RouteDecision: ...

    def plan(
        self,
        question: str,
        catalog: list[dict],
        bas: list[tuple[str, str]],
        today: date,
        errors: list[str],
        previous: MetricRequest | None,
        saved_queries: list[dict] = (),
        history: list[dict] = (),
    ) -> PlannedRequest | MetricRequest: ...

    def answer(
        self,
        question: str,
        request: MetricRequest,
        result: dict,
        catalog: list[dict],
        bad: list[str],
    ) -> str: ...

    def define(self, question: str, catalog: list[dict]) -> str: ...


def chat_model(settings: AgentSettings, model_id: str) -> BaseChatModel:
    if settings.provider == "bedrock":
        from langchain_aws import ChatBedrockConverse

        return ChatBedrockConverse(model=model_id, region_name=settings.aws_region, temperature=0)
    if settings.provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
        return ChatAnthropic(model=model_id, api_key=key, temperature=0, max_tokens=2048)
    if settings.provider == "openai":  # temporary, local only (ADR-0003)
        from langchain_openai import ChatOpenAI

        key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else None
        # No temperature: OpenAI's reasoning models reject anything but the default. The token
        # cap includes reasoning tokens, hence higher than for the other providers.
        return ChatOpenAI(model=model_id, api_key=key, max_tokens=8192)
    from langchain_ollama import ChatOllama

    return ChatOllama(model=model_id, base_url=settings.ollama_url, temperature=0)


class LLMBrain:
    def __init__(self, router: BaseChatModel, planner: BaseChatModel) -> None:
        self._router = router.with_structured_output(RouteDecision)
        self._planner = planner.with_structured_output(PlannedRequest)
        self._writer = planner

    @classmethod
    def from_settings(cls, settings: AgentSettings) -> "LLMBrain":
        router_id, planner_id = settings.models()
        return cls(chat_model(settings, router_id), chat_model(settings, planner_id))

    def route(self, question, history=()):
        return self._router.invoke(
            prompts.ROUTER.format(question=question, history=prompts.history_text(history))
        )

    def plan(self, question, catalog, bas, today, errors, previous, saved_queries=(), history=()):
        feedback = (
            prompts.PLAN_FEEDBACK.format(
                errors="\n".join(f"- {e}" for e in errors),
                previous=previous.model_dump_json() if previous else "none",
            )
            if errors
            else ""
        )
        return self._planner.invoke(
            prompts.PLANNER.format(
                today=today.isoformat(),
                bas="\n".join(f"{code}: {name}" for code, name in bas),
                catalog=prompts.catalog_json(catalog),
                saved_queries=prompts.saved_queries_text(saved_queries),
                history=prompts.history_text(history, with_requests=True),
                feedback=feedback,
                question=question,
            )
        )

    def answer(self, question, request, result, catalog, bad):
        used = [m for m in catalog if m["name"] in request.metrics]
        feedback = prompts.ANSWER_FEEDBACK.format(bad=bad) if bad else ""
        message = self._writer.invoke(
            prompts.ANSWER.format(
                question=question,
                request=request.model_dump_json(),
                definitions=json.dumps(
                    [{k: m[k] for k in ("name", "description", "unit")} for m in used]
                ),
                columns=result["columns"],
                rows="\n".join(str(r) for r in result["rows"][:200]),
                feedback=feedback,
            )
        )
        return message.content if isinstance(message.content, str) else str(message.content)

    def define(self, question, catalog):
        message = self._writer.invoke(
            prompts.DEFINE.format(catalog=prompts.catalog_json(catalog), question=question)
        )
        return message.content if isinstance(message.content, str) else str(message.content)
