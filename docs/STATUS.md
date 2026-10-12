# GridPulse — Status

Single source of truth for what is done and what is next. Read at the start of every session; update before ending one.
A step is ticked only with the date and the evidence (command/output) that proved its "done when" check.
Human-only tasks live in the git-ignored `TODO.md` and are referenced here as `TODO #N`.

Last updated: 2026-10-12
Repo: https://github.com/debolai/gridpulse

## Current focus
- Phase A2 — `region-data` extractor

## Next up
1. A2: `ingestion/` package in the uv workspace; record real API responses as respx fixtures
2. A2: paginated, sorted, rate-limited extractor with pydantic validation and completeness assert
3. A2: raw JSON + manifest to `gridpulse-local-raw`; PyIceberg append to `raw.eia_region_data` (catalog via config: REST locally, Glue on AWS)
4. A2: done-check: rerun of a window adds no new distinct rows

## Blockers
- TODO #6 (AWS credentials: none configured on this Mac yet) blocks the A3 `aws` target and A6.

## Phase A — MVP slice
- [x] **A0 Foundations** — 2026-10-12 — done when `make lint test` passes locally and in GitHub Actions
  - [x] git init, `.gitignore` (TODO.md, .env), uv workspace, ruff, yamllint, pre-commit, Makefile — 2026-10-12
  - [x] Blueprint moved to `docs/blueprint.md` with changelog; STATUS.md, TODO.md, ADR template, CLAUDE.md — 2026-10-12
  - [x] `make lint test` passes locally — 2026-10-12
  - [x] CI passes in GitHub Actions — 2026-10-12 — https://github.com/debolai/gridpulse/actions/runs/38279302910 (commit 0dbf97b)
- [x] **A1 Local lake** — 2026-10-12 — done when Trino creates/reads an Iceberg table and `make reset && make up-lake` works from scratch
  - Evidence: `make reset` (0 volumes left) → `make up-lake` (12.7 s) → `make test-integration` 1 passed; test schema dropped afterwards. Idle memory ~1.1 GB (Trino 890 MB).
  - Pinned: Postgres 18.6, SeaweedFS 4.47 (replaces MinIO, ADR-0001), Lakekeeper 0.13.6, Trino 483, curl 8.22.0 — all tag + digest.
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

## Findings to fold into the build
- 2026-10-12: `region-data` returns day-ahead forecast (`DF`) rows for future hours (latest PJM row was a DF for 2026-10-13T04 UTC). Freshness checks must use the latest *demand* (`D`) hour, not max(`period`). Values confirmed as strings.

## Session log
- 2026-10-12 — Plan agreed (offline local mode, MVP first). A0 scaffolding created; lint and tests pass locally. Next: GitHub repo, then A1.
- 2026-10-12 — TODO #1, #2, #3, #5 done (#6 still open: no AWS credentials found). Pushed to GitHub; CI green. A0 complete. Next: A1.
- 2026-10-12 — TODO #4 done: EIA key verified with a live call (HTTP 200).
- 2026-10-12 — A1 complete: local lake (SeaweedFS + Lakekeeper + Trino) up from scratch in ~13 s; Iceberg round-trip test passes. MinIO images discontinued → SeaweedFS (ADR-0001). Next: A2.
