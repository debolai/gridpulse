.DEFAULT_GOAL := help
SHELL := /bin/bash

COMPOSE := docker compose -f local/compose.yaml

.PHONY: help setup lint secrets-staged secrets-history format test test-integration status doctor clean \
	up-lake up-orch up down ps logs reset prune trino extract extract-sample extract-weather extract-weather-aws dag-check images \
	dbt-deps dbt-build dbt-test dbt-docs dbt-drop \
	tf-bootstrap tf-init tf-plan tf-apply tf-fmt aws-whoami extract-sample-aws dbt-build-aws \
	aws-plan aws-up aws-down aws-status aws-ui \
	semantic-manifest semantic-api mf bedrock-check openai-check agent-api agent-ui agent-eval demo-gif

help: ## List available commands
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

setup: ## Install pinned dev tools and git hooks
	uv sync --locked
	uv run pre-commit install

lint: ## Run all linters (no changes made)
	uv run ruff format --check .
	uv run ruff check .
	uv run yamllint --strict .

# gitleaks reads text on stdin, so it never runs git inside the container (where git can fail
# and gitleaks would then report "no leaks" instead of an error).
GITLEAKS := docker run --rm -i -v "$(CURDIR)/.gitleaks.toml:/.gitleaks.toml:ro" \
	ghcr.io/gitleaks/gitleaks:v8.30.1@sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f \
	stdin --config /.gitleaks.toml --redact --no-banner --verbose

secrets-staged: ## Scan staged changes for API keys and other secrets (pre-commit hook)
	@set -o pipefail; git diff --cached --no-color | $(GITLEAKS)

secrets-history: ## Scan every commit for API keys and other secrets (CI)
	@set -o pipefail; git log --all -p --no-color | $(GITLEAKS)

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

up-orch: images ## Start the lake plus Airflow (UI: http://localhost:8088), ~5 GB
	$(COMPOSE) --profile lake --profile orch up -d --wait
	@echo "Airflow: http://localhost:8088   Trino: http://localhost:8080"

up: up-orch ## Start everything built so far

images: ## Build the local task images Airflow launches (extractor, dbt)
	docker build -q -f ingestion/Dockerfile -t gridpulse/ingestion:local . >/dev/null
	docker build -q -f transform/Dockerfile -t gridpulse/transform:local . >/dev/null
	@echo "built gridpulse/ingestion:local gridpulse/transform:local"

dag-check: ## DAG integrity: imports, no catchup, retries, timeouts, EIA pool
	$(COMPOSE) --profile orch run --rm --no-deps --entrypoint python airflow /opt/airflow/tests/dag_integrity.py

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
ROUTE ?= region-data

extract: ## Run the extractor, e.g. make extract ARGS="eia --route region-data --start 2026-10-01 --end 2026-10-08"
	$(COMPOSE) run --rm --build extractor $(ARGS)

extract-sample: ## Load one route for the sample BAs: make extract-sample START=2026-10-01 END=2026-10-08 [ROUTE=fuel-type-data]
	$(COMPOSE) run --rm --build extractor eia --route $(ROUTE) \
		--start $(START) --end $(END) --respondents $(SAMPLE_BAS)

# Stations come from the dbt seed, so the mapping lives in one place.
WEATHER_STATIONS = $(shell awk -F, 'NR>1 {print $$2}' transform/seeds/ba_weather_stations.csv | sort -u | paste -sd, -)

extract-weather: ## Load NOAA GHCNh weather for the seed's stations: make extract-weather START=2026-07-01 END=2026-10-13
	$(COMPOSE) run --rm --build extractor noaa --stations $(WEATHER_STATIONS) --start $(START) --end $(END)

extract-weather-aws: ## Same as extract-weather, but into the AWS dev lake
	AWS_PROFILE=$(AWS_PROFILE) infra/scripts/extract-aws.sh noaa --stations $(WEATHER_STATIONS) \
		--start $(START) --end $(END)

extract-sample-aws: ## Same as extract-sample, but into the AWS dev lake (S3 + Glue)
	AWS_PROFILE=$(AWS_PROFILE) infra/scripts/extract-aws.sh eia --route $(ROUTE) \
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

BEDROCK_CHECK_MODELS ?= us.anthropic.claude-haiku-5-5 us.anthropic.claude-sonnet-5-5 \
	us.anthropic.claude-haiku-4-5-20251001-v1:0 us.anthropic.claude-sonnet-4-6

bedrock-check: ## Send each Claude model on Bedrock one tiny message and report which ones work
	@for m in $(BEDROCK_CHECK_MODELS); do \
		out=$$(aws bedrock-runtime converse --profile $(AWS_PROFILE) --region us-east-1 --model-id $$m \
			--messages '[{"role":"user","content":[{"text":"Reply with the single word: ready"}]}]' \
			--inference-config '{"maxTokens":5}' --query 'output.message.content[0].text' --output text 2>&1); \
		case "$$out" in \
			*use\ case\ details*) msg="needs the Anthropic use-case form (TODO #7)";; \
			*not\ available\ for\ this\ account*) msg="not enabled for this account yet";; \
			*being\ verified*) msg="account still being verified";; \
			*ERROR*) msg="error: $$(echo "$$out" | tail -1 | cut -c1-90)";; \
			*) msg="OK ($$out)";; \
		esac; printf '  %-45s %s\n' "$$m" "$$msg"; done

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

# --- Assistant (agent/) ---------------------------------------------------------
# Needs the semantic API running (make semantic-api) and a model provider:
# GRIDPULSE_AGENT_PROVIDER=bedrock (default; AWS login + TODO #7) | anthropic | ollama
# | openai (temporary, local only, until Bedrock quotas are lifted: ADR-0003, TODO #11)

openai-check: ## Confirm the OpenAI key in .env can call the agent's two models (one tiny request each)
	uv run --quiet python -m gridpulse_agent.openai_check

agent-api: ## Serve the assistant at http://localhost:8091/docs
	AWS_PROFILE=$(AWS_PROFILE) uv run gridpulse-agent

agent-ui: ## Open the Streamlit demo UI (talks to agent-api)
	uv run streamlit run agent/src/gridpulse_agent/ui.py

demo-gif: ## Record docs/assets/demo.gif from the running UI (needs lake, semantic-api, agent-api, agent-ui)
	uv run --quiet --with playwright==1.63.0 python agent/scripts/demo_gif.py

agent-eval: ## Score the planner on the golden question set (fails below 90%)
	AWS_PROFILE=$(AWS_PROFILE) uv run gridpulse-agent-eval

# --- AWS demo (compute: VPC + EKS + serving layer) ---------------------------------
# About $0.20-0.25/hour while up; nothing but the foundation while down.

aws-plan: ## Review what aws-up will create (compute stack plan)
	AWS_PROFILE=$(AWS_PROFILE) terraform -chdir=infra/terraform/envs/$(TF_ENV)/compute init -input=false \
		-backend-config="bucket=gridpulse-tfstate-$$(aws sts get-caller-identity --profile $(AWS_PROFILE) --query Account --output text)" >/dev/null
	AWS_PROFILE=$(AWS_PROFILE) terraform -chdir=infra/terraform/envs/$(TF_ENV)/compute plan -input=false

aws-up: ## Create the demo on EKS, deploy, smoke test (~15-20 min)
	AWS_PROFILE=$(AWS_PROFILE) infra/scripts/aws-up.sh

aws-down: ## Destroy the demo compute and verify nothing billable is left
	AWS_PROFILE=$(AWS_PROFILE) infra/scripts/aws-down.sh

aws-status: ## Is the demo up? (cluster, nodes, pods)
	@aws eks list-clusters --profile $(AWS_PROFILE) --query clusters --output text | grep -q gridpulse \
		&& kubectl --context gridpulse-$(TF_ENV) -n gridpulse get pods -o wide \
		|| echo "AWS demo is down (no EKS cluster)."

aws-ui: ## Open the demo UI through a port-forward: http://localhost:8501
	kubectl --context gridpulse-$(TF_ENV) -n gridpulse port-forward svc/agent-ui 8501:8501

