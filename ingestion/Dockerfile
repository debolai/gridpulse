# Extractor image. Build from the repo root: docker build -f ingestion/Dockerfile .
# Multi-stage: uv resolves the locked deps in a builder; the runtime has only the venv, as non-root.

FROM ghcr.io/astral-sh/uv:0.12.19@sha256:04d046b13e60d6bcec73cbc5e1cad25d680dea90c8573340950a0ac2d1aef424 AS uv

FROM python:3.12.15-slim-trixie@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1 AS builder
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app

# Dependencies first, so code changes don't reinstall them.
# uv reads every workspace member's pyproject.toml to use the shared lockfile, so all of them
# are copied (manifests only; just this component's source is copied below).
COPY pyproject.toml uv.lock README.md ./
COPY ingestion/pyproject.toml ingestion/pyproject.toml
COPY semantic/pyproject.toml semantic/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --package gridpulse-ingestion --no-install-workspace

COPY ingestion/src ingestion/src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --package gridpulse-ingestion --no-editable

FROM python:3.12.15-slim-trixie@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
LABEL com.gridpulse.project=gridpulse com.gridpulse.component=ingestion
RUN useradd --create-home --uid 10001 gridpulse
COPY --from=builder --chown=gridpulse:gridpulse /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER gridpulse
WORKDIR /home/gridpulse
ENTRYPOINT ["gridpulse-extract"]
