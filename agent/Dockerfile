# Assistant image: LangGraph agent API (default) and the Streamlit UI (same image, different
# command). Build from the repo root: docker build -f agent/Dockerfile .

FROM ghcr.io/astral-sh/uv:0.12.19@sha256:04d046b13e60d6bcec73cbc5e1cad25d680dea90c8573340950a0ac2d1aef424 AS uv

FROM python:3.12.15-slim-trixie@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1 AS builder
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY ingestion/pyproject.toml ingestion/pyproject.toml
COPY semantic/pyproject.toml semantic/pyproject.toml
COPY agent/pyproject.toml agent/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --package gridpulse-agent --no-install-workspace
COPY agent/src agent/src
COPY agent/evals agent/evals
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --package gridpulse-agent --no-editable

FROM python:3.12.15-slim-trixie@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
LABEL com.gridpulse.project=gridpulse com.gridpulse.component=agent
RUN useradd --create-home --uid 10001 gridpulse
COPY --from=builder --chown=gridpulse:gridpulse /app/.venv /app/.venv
COPY --chown=gridpulse:gridpulse agent/evals /app/agent/evals
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 HOST=0.0.0.0 PORT=8091 \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    GRIDPULSE_AGENT_GOLDEN_SET=/app/agent/evals/golden.yaml
USER gridpulse
WORKDIR /home/gridpulse
EXPOSE 8091 8501
ENTRYPOINT ["gridpulse-agent"]
