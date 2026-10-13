"""`make openai-check`: confirm the OpenAI key in .env can call the agent's two models.
One tiny request per model (a fraction of a cent), through the same client the agent uses, so a
restricted key needs no extra scopes. Temporary, local only: delete with the openai provider
(ADR-0003)."""

import sys

import openai

from gridpulse_agent.brain import chat_model
from gridpulse_agent.config import AgentSettings


def main() -> None:
    settings = AgentSettings(provider="openai")
    if not settings.openai_api_key:
        sys.exit("GRIDPULSE_AGENT_OPENAI_API_KEY is not set in .env (TODO #12)")
    failed = False
    for model in dict.fromkeys(settings.models()):
        try:
            chat_model(settings, model).invoke("Reply with the single word: ready")
            print(f"{model:<14} OK")
        except openai.APIStatusError as e:
            failed = True
            print(f"{model:<14} FAILED ({e.status_code}): {e.message[:160]}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
