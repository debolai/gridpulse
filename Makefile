.DEFAULT_GOAL := help
SHELL := /bin/bash

.PHONY: help setup lint format test status doctor clean

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

test: ## Run the test suite
	uv run pytest

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
