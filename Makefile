.DEFAULT_GOAL := help
SHELL := /bin/bash

COMPOSE := docker compose -f local/compose.yaml

.PHONY: help setup lint format test test-integration status doctor clean \
	up-lake up down ps logs reset prune trino extract extract-sample \
	dbt-deps dbt-build dbt-test dbt-docs dbt-drop \
	tf-bootstrap tf-init tf-plan tf-apply tf-fmt aws-whoami extract-sample-aws dbt-build-aws \
	semantic-manifest semantic-api mf bedrock-check

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
	rm -rf .pytest_cache .ruff_cache transform/target transform/logs transform/dbt_packages
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

# --- Ingestion ---------------------------------------------------------------

# Local data is a sample (plan: ~6 BAs x ~3 months); the full history only runs on AWS.
SAMPLE_BAS ?= CISO,ERCO,ISNE,MISO,NYIS,PJM

extract: ## Run the extractor, e.g. make extract ARGS="eia --route region-data --start 2026-10-01 --end 2026-10-08"
	$(COMPOSE) run --rm --build extractor $(ARGS)

extract-sample: ## Load region-data for the sample BAs: make extract-sample START=2026-10-01 END=2026-10-08
	$(COMPOSE) run --rm --build extractor eia --route region-data \
		--start $(START) --end $(END) --respondents $(SAMPLE_BAS)

extract-sample-aws: ## Same as extract-sample, but into the AWS dev lake (S3 + Glue)
	AWS_PROFILE=$(AWS_PROFILE) infra/scripts/extract-aws.sh eia --route region-data \
		--start $(START) --end $(END) --respondents $(SAMPLE_BAS)

# --- dbt (transform/) ---------------------------------------------------------

DBT := DBT_PROJECT_DIR=transform DBT_PROFILES_DIR=transform uv run --quiet dbt

dbt-deps: ## Install dbt packages (pinned in transform/package-lock.yml)
	$(DBT) deps

dbt-build: dbt-deps ## Build and test all dbt models on the local lake (DBT_TARGET=aws for Athena)
	$(DBT) build $(ARGS)

dbt-build-aws: dbt-deps ## Build and test all dbt models on Athena (AWS dev)
	AWS_PROFILE=$(AWS_PROFILE) DBT_TARGET=aws $(DBT) build $(ARGS)

dbt-test: ## Run dbt data and unit tests only
	$(DBT) test $(ARGS)

dbt-docs: ## Generate and serve dbt docs at http://localhost:8081
	$(DBT) docs generate && $(DBT) docs serve --port 8081

dbt-drop: ## Drop throwaway schemas built with a prefix: make dbt-drop PREFIX=ci_pr_42
	$(DBT) run-operation drop_prefixed_schemas --args '{prefix: $(PREFIX)}'

# --- AWS foundation (Terraform) ------------------------------------------------
# Always-on, low-cost layer: buckets, Glue, Athena workgroups, budgets. Always plan, review,
# then apply the saved plan. Uses the SSO profile; renew with `aws sso login --profile gridpulse`.

AWS_PROFILE ?= gridpulse
TF_ENV ?= dev
TF_DIR := infra/terraform/envs/$(TF_ENV)/foundation
TF := AWS_PROFILE=$(AWS_PROFILE) terraform -chdir=$(TF_DIR)

aws-whoami: ## Show which AWS account and role you're using
	@aws sts get-caller-identity --profile $(AWS_PROFILE) --query Arn --output text

BEDROCK_CHECK_MODEL ?= us.anthropic.claude-haiku-5-5

bedrock-check: ## Send Claude on Bedrock one tiny message (prints "ready" when access works)
	@aws bedrock-runtime converse --profile $(AWS_PROFILE) --region us-east-1 \
		--model-id $(BEDROCK_CHECK_MODEL) \
		--messages '[{"role":"user","content":[{"text":"Reply with the single word: ready"}]}]' \
		--inference-config '{"maxTokens":5}' --query 'output.message.content[0].text' --output text

tf-bootstrap: ## One-time: create the Terraform state bucket (idempotent)
	AWS_PROFILE=$(AWS_PROFILE) infra/scripts/bootstrap-state.sh

tf-init: ## Initialise Terraform against the remote state bucket
	$(TF) init -input=false -backend-config="bucket=gridpulse-tfstate-$$(aws sts get-caller-identity --profile $(AWS_PROFILE) --query Account --output text)"

tf-plan: ## Show what Terraform would change (saved to foundation.tfplan)
	$(TF) plan -input=false -out=foundation.tfplan

tf-apply: ## Apply the reviewed plan from `make tf-plan` (nothing else)
	$(TF) apply -input=false foundation.tfplan

tf-fmt: ## Format and validate Terraform
	terraform fmt -recursive infra/terraform
	$(TF) validate

# --- Semantic layer (semantic/) -------------------------------------------------

semantic-manifest: ## Rebuild the semantic manifest (full parse: partial parsing misses metric edits)
	$(DBT) parse --no-partial-parse

semantic-api: semantic-manifest ## Serve the semantic API at http://localhost:8090/docs (DBT_TARGET=aws for Athena)
	DBT_PROJECT_DIR=transform DBT_PROFILES_DIR=transform AWS_PROFILE=$(AWS_PROFILE) uv run gridpulse-semantic

mf: ## Run MetricFlow directly, e.g. make mf ARGS="query --metrics demand --group-by balancing_authority"
	cd transform && DBT_PROFILES_DIR=. AWS_PROFILE=$(AWS_PROFILE) uv run --quiet mf $(ARGS)

