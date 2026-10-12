.DEFAULT_GOAL := help
SHELL := /bin/bash

COMPOSE := docker compose -f local/compose.yaml

.PHONY: help setup lint format test test-integration status doctor clean \
	up-lake up down ps logs reset prune trino

help: ## List available commands
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

setup: ## Install pinned dev tools and git hooks
	uv sync --locked
	uv run pre-commit install

lint: ## Run all linters (no changes made)
	uv run ruff format --check .
	uv run ruff check .
	uv run yamllint --strict .

format: ## Auto-format Python
	uv run ruff format .
	uv run ruff check --fix .

test: ## Run unit tests (no services needed)
	uv run pytest

test-integration: ## Run integration tests against the running local stack
	uv run pytest -m integration

status: ## Show current focus and next tasks from docs/STATUS.md
	@awk '/^## Current focus/,/^## Blockers/' docs/STATUS.md | sed '$$d'
	@if [ -f TODO.md ] && grep -q '\[ \]' TODO.md; then \
		echo "🔔 Blocking human tasks in TODO.md:"; \
		awk '/^## Blocking/{f=1;next} /^## /{f=0} f && /^[0-9]+\. \[ \]/' TODO.md; fi

doctor: ## Check Docker memory and disk headroom
	@mem=$$(docker info --format '{{.MemTotal}}' 2>/dev/null) || { echo "Docker is not running"; exit 1; }; \
	gb=$$((mem / 1073741824)); echo "Docker memory limit: $${gb} GB"; \
	if [ $$gb -lt 12 ]; then echo "⚠️  Raise Docker Desktop memory to 14-16 GB (Settings → Resources)"; fi
	@docker system df
	@df -h . | tail -1 | awk '{print "Disk free: " $$4}'

clean: ## Remove caches and build output (keeps data)
	rm -rf .pytest_cache .ruff_cache transform/target transform/logs
	find . -name __pycache__ -type d -prune -not -path './.venv/*' -exec rm -rf {} +

# --- Local stack -------------------------------------------------------------

up-lake: ## Start the lake: Postgres, SeaweedFS (S3), Lakekeeper, Trino (~3 GB)
	$(COMPOSE) --profile lake up -d --wait
	@echo "Trino: http://localhost:8080   Lakekeeper UI: http://localhost:8181/ui   S3: http://localhost:8333"

up: up-lake ## Start everything built so far (orch/app profiles join in A4-A6)

down: ## Stop all containers, keep data
	$(COMPOSE) --profile '*' down

ps: ## Show running GridPulse containers and their memory use
	@$(COMPOSE) --profile '*' ps
	@docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}' \
		$$(docker ps -q --filter label=com.gridpulse.project=gridpulse) 2>/dev/null || true

logs: ## Follow logs (optionally: make logs s=trino)
	$(COMPOSE) --profile '*' logs -f --tail 100 $(s)

trino: ## Open a Trino SQL shell on the local lake
	$(COMPOSE) exec trino trino --catalog lake

reset: ## Delete ALL local data (containers + volumes), asks first
	@read -p "Delete all local GridPulse data (lake, catalog, Postgres)? [y/N] " ans; [ "$$ans" = y ]
	$(COMPOSE) --profile '*' down -v --remove-orphans

prune: ## Remove GridPulse containers, volumes and images, plus dangling build cache
	@read -p "Remove GridPulse images and data? They will re-download on next 'make up'. [y/N] " ans; [ "$$ans" = y ]
	$(COMPOSE) --profile '*' down -v --rmi all --remove-orphans
	docker builder prune -f

