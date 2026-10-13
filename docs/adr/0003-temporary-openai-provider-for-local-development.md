# ADR-0003: Temporary OpenAI API provider for local development while Bedrock is blocked

Status: Accepted (temporary; revert when TODO #11 is resolved)
Date: 2026-10-13

## Context
The blueprint runs the agent on Claude on Amazon Bedrock, locally and on EKS, so no API key
exists to leak. This new AWS account is held at a Bedrock quota of 0 for every model family:
Claude, OpenAI gpt-oss and Amazon Nova all fail with "Too many tokens per day", and OpenAI's
GPT-5.5/6.x on Bedrock are "not available for this account" (tested 2026-10-13). Only AWS Support
can lift that (TODO #11, typically 1-3 business days). Phase A cannot close without live model
calls: the A5 eval (≥ 90%) and the A6 smoke question both need them.

## Decision
Until Bedrock works, the agent may use the OpenAI API directly (`GRIDPULSE_AGENT_PROVIDER=openai`)
on the laptop only:
- Models: GPT-6 Luna routes, GPT-6.1 Sol plans and answers (overridable by env).
- The key lives in `.env` (git-ignored, excluded from images), is a `SecretStr`, and comes from a
  dedicated OpenAI project with a hard budget of $10-20 and auto-recharge off.
- Key-based providers refuse to start inside Kubernetes, so the deployed agent stays on Bedrock.
- gitleaks runs in pre-commit and CI (full history) to block committed keys.

The Bedrock decision in the blueprint is unchanged; this is a time-boxed local exception.

## Alternatives considered
- Wait for AWS Support: blocks Phase A for days.
- Another model family on Bedrock: the restriction is account-wide (tested).
- Anthropic API directly: same key trade-off, no code change; the project owner chose OpenAI.
- Deploy the key to EKS (Secrets Manager): reverses "no API keys in the cloud" for a demo
  that can wait for Bedrock.
- Ollama: free, but small local models are unlikely to reach the 90% eval target.

## Consequences
- The eval result on GPT models does not prove the Claude configuration; rerun `make agent-eval`
  on Bedrock after the revert before ticking A5 for good.
- Prompts may get tuned for GPT behaviour; keep changes model-neutral where possible.

## Revert checklist (when `make bedrock-check` shows OK)
1. `make agent-eval` on Bedrock (default provider) passes ≥ 90%.
2. Remove `openai` from `agent/src/gridpulse_agent/config.py` (`DEFAULT_MODELS`, the provider
   literal, `openai_api_key`) and `brain.py`; delete `openai_check.py`, the `openai-check`
   Makefile target and its test in `agent/tests/test_config.py`; `uv remove --package
   gridpulse-agent langchain-openai`. Keep the Kubernetes guard (it still covers `anthropic`).
3. Remove `GRIDPULSE_AGENT_PROVIDER` / `GRIDPULSE_AGENT_OPENAI_API_KEY` from `.env`, then
   revoke the key and archive the OpenAI project (human task).
4. Re-record the demo with `make demo-gif` on Bedrock and remove the "Temporary" note from
   the README's MVP section.
5. Mark this ADR "Superseded (reverted YYYY-MM-DD)", remove the temporary exception from the
   blueprint's Bedrock decision, add a changelog line, and update STATUS.md. gitleaks stays.
