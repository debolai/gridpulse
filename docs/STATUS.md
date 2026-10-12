# GridPulse — Status

Single source of truth for what is done and what is next. Read at the start of every session; update before ending one.
A step is ticked only with the date and the evidence (command/output) that proved its "done when" check.
Human-only tasks live in the git-ignored `TODO.md` and are referenced here as `TODO #N`.

Last updated: 2026-10-12
Repo: https://github.com/debolai/gridpulse

## Current focus
- Phase A4 — Semantic layer (Trino half of the spike first; the Athena half and A3's `aws` parity wait on TODO #6)

## Next up
1. A4 spike: install `dbt-metricflow`; compile and run a sum, a ratio and a cumulative metric on Trino; record an ADR
2. A4: time spine model; semantic model on `fct_grid_hourly`; metrics `demand`, `peak_demand`, `forecast_error_mape`, `forecast_bias`, `data_completeness`
3. A4: FastAPI semantic API (`GET /metrics`, `POST /compile`, `POST /query`) + SQL ground-truth tests
4. When TODO #6 lands: A3 `aws` target parity (Terraform foundation first), then the Athena half of the A4 spike

## Blockers
- TODO #9 (budget-alert email) blocks the first Terraform apply (foundation), and so the A3 `aws` target. AWS profile `gridpulse` is ready (TODO #6 done 2026-10-12).

## Phase A — MVP slice
- [x] **A0 Foundations** — 2026-10-12 — done when `make lint test` passes locally and in GitHub Actions
  - [x] git init, `.gitignore` (TODO.md, .env), uv workspace, ruff, yamllint, pre-commit, Makefile — 2026-10-12
  - [x] Blueprint moved to `docs/blueprint.md` with changelog; STATUS.md, TODO.md, ADR template, CLAUDE.md — 2026-10-12
  - [x] `make lint test` passes locally — 2026-10-12
  - [x] CI passes in GitHub Actions — 2026-10-12 — https://github.com/debolai/gridpulse/actions/runs/38279302910 (commit 0dbf97b)
- [x] **A1 Local lake** — 2026-10-12 — done when Trino creates/reads an Iceberg table and `make reset && make up-lake` works from scratch
  - Evidence: `make reset` (0 volumes left) → `make up-lake` (12.7 s) → `make test-integration` 1 passed; test schema dropped afterwards. Idle memory ~1.1 GB (Trino 890 MB).
  - Pinned: Postgres 18.6, SeaweedFS 4.47 (replaces MinIO, ADR-0001), Lakekeeper 0.13.6, Trino 483, curl 8.22.0 — all tag + digest.
- [x] **A2 region-data extractor** — 2026-10-12 — done when a rerun adds no new distinct rows and the completeness assert passes
  - Evidence: `make extract-sample START=2026-10-01 END=2026-10-08` twice → 3,984/3,984 rows (completeness OK), same run_id; Trino: 7,968 raw rows, 3,984 distinct hashes = 3,984 distinct keys. `make test-integration` 2 passed (rerun test in a throwaway namespace, cleaned up). 31 unit tests on recorded fixtures.
- [ ] **A3 dbt slice** — done when `dbt build` passes on `local` and `aws` targets with equal row counts for a fixed window
  - [x] Local (Trino) half — 2026-10-12. Evidence: `make dbt-build` PASS=26 (1 seed, 4 models, 18 data tests, 3 unit tests incl. DST spring-forward/fall-back, Arizona and the A→B→A revert case). Incremental vs `--full-refresh` in a check schema: 14,832 = 14,832 rows, 0 differences either way. `make test-integration` 3 passed, no test schemas left.
  - [ ] AWS (Athena) half — blocked on TODO #6. Check then: contract `data_type`s (Trino names) and `timestamptz` handling on Athena.
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
- 2026-10-12: EIA's BA "Time Zone" is a reporting convention: EPE, PNM and WACM are labelled "Arizona" (MST all year) but observe DST. Seed keeps both `eia_time_zone` and a geographic IANA `time_zone`.
- 2026-10-12: one extraction attempt (2026-10-05..12) failed and its manifest was overwritten by the successful retry, so the cause is unknown. Fixed: manifests are now kept per attempt.
- 2026-10-12: ERCO is missing 24 of 168 hours of `DF` and `TI` in 2026-10-01..07 (D and NG complete). Real gap for B1 quality flags and `data_completeness`.
- 2026-10-12: EIA `end` is inclusive; extractor windows are half-open [start, end) and send end − 1h. `total` is a string. `warnings` sit at the top level of the response.
- 2026-10-12: Lakekeeper (STS off) uses remote signing: clients get no storage keys, and PyIceberg must use fsspec (`s3fs`). On AWS, Glue + IAM roles use PyArrow IO instead.
- 2026-10-12: `region-data` returns day-ahead forecast (`DF`) rows for future hours (latest PJM row was a DF for 2026-10-13T04 UTC). Freshness checks must use the latest *demand* (`D`) hour, not max(`period`). Values confirmed as strings.

## Session log
- 2026-10-12 — Plan agreed (offline local mode, MVP first). A0 scaffolding created; lint and tests pass locally. Next: GitHub repo, then A1.
- 2026-10-12 — TODO #1, #2, #3, #5 done (#6 still open: no AWS credentials found). Pushed to GitHub; CI green. A0 complete. Next: A1.
- 2026-10-12 — TODO #4 done: EIA key verified with a live call (HTTP 200).
- 2026-10-12 — A1 complete: local lake (SeaweedFS + Lakekeeper + Trino) up from scratch in ~13 s; Iceberg round-trip test passes. MinIO images discontinued → SeaweedFS (ADR-0001). Next: A2.
- 2026-10-12 — A2 complete: region-data extractor (container), 1 week × 6 BAs loaded locally, rerun idempotent. Next: A3 dbt slice.
- 2026-10-12 — A3 local half complete: dbt project (Trino + Athena targets), EIA-sourced BA seed, staging → latest values → dim/fct with contracts; incremental proven equal to full rebuild. Next: A4 spike on Trino.
- 2026-10-12 — TODO #6 done: AWS account with IAM Identity Center admin, SSO profile `gridpulse` (us-east-1), root MFA on. Waiting on budget email (#9).
