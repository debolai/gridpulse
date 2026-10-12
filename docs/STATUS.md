# GridPulse — Status

Single source of truth for what is done and what is next. Read at the start of every session; update before ending one.
A step is ticked only with the date and the evidence (command/output) that proved its "done when" check.
Human-only tasks live in the git-ignored `TODO.md` and are referenced here as `TODO #N`.

Last updated: 2026-10-12

## Current focus
- Phase A0 — Foundations (almost done; CI-in-Actions check waits on TODO #5)

## Next up
1. A0: push to GitHub and confirm CI passes (blocked on TODO #5)
2. A1: `local/compose.yaml` with profiles `lake`, `orch`, `app`, memory limits, `make up-*`/`down`/`reset`/`prune`
3. A1: MinIO + Lakekeeper + Trino bootstrap; prove create/read of an Iceberg table
4. A2: `region-data` extractor (needs EIA key — TODO #4)

## Blockers
- TODO #4 (EIA API key) blocks A2 live pulls. Fixture-based work can proceed.
- TODO #5 (GitHub repo) blocks the A0 CI check.

## Phase A — MVP slice
- [ ] **A0 Foundations** — done when `make lint test` passes locally and in GitHub Actions
  - [x] git init, `.gitignore` (TODO.md, .env), uv workspace, ruff, yamllint, pre-commit, Makefile — 2026-10-12
  - [x] Blueprint moved to `docs/blueprint.md` with changelog; STATUS.md, TODO.md, ADR template, CLAUDE.md — 2026-10-12
  - [x] `make lint test` passes locally — 2026-10-12
  - [ ] CI passes in GitHub Actions
- [ ] **A1 Local lake** — done when Trino creates/reads an Iceberg table in MinIO and `make reset && make up-lake` works from scratch
- [ ] **A2 region-data extractor** — done when a rerun adds no new distinct rows and the completeness assert passes
- [ ] **A3 dbt slice** — done when `dbt build` passes on `local` and `aws` targets with equal row counts for a fixed window
- [ ] **A4 Semantic layer** — done when `mf validate-configs` passes and every metric matches its reference SQL
- [ ] **A5 Minimal agent** — done when eval accuracy ≥ 90% and an injected wrong number is caught
- [ ] **A6 Scheduling + AWS** — done when `make aws-down && make aws-up` restores a demo that answers the smoke question
- [ ] **MVP checkpoint** — README MVP section, demo GIF, "still to come" list

## Phase B — Depth
- [ ] B1 Data coverage (fuel, interchange, NOAA, flags, revisions, snapshots, reconciliation, Elementary)
- [ ] B2 Orchestration on k3d (Airflow 3 Helm, KubernetesExecutor, Cosmos, 7 DAGs, pool, alerts) + full backfill on AWS
- [ ] B3 Full semantic layer (12 metrics, saved queries, allow-list, cache)
- [ ] B4 Full agent (clarify, inspect, checkpointer, 50-question golden set, nightly eval)
- [ ] B5 CI/CD (slim CI, local-target CI, Terraform plan comments, cd.yml with approval, rollback, pr-cleanup)
- [ ] B6 Polish (README, video, dbt docs, ADR index, cost report, data-issue write-up)
- [ ] B7 Optional (hosted dbt Semantic Layer demo, Cube comparison)

## Deferred / later
- (empty — park scope creep here instead of starting it)

## Session log
- 2026-10-12 — Plan agreed (offline local mode, MVP first). A0 scaffolding created; lint and tests pass locally. Next: GitHub repo, then A1.
