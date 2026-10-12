# GridPulse — Status

Single source of truth for what is done and what is next. Read at the start of every session; update before ending one.
A step is ticked only with the date and the evidence (command/output) that proved its "done when" check.
Human-only tasks live in the git-ignored `TODO.md` and are referenced here as `TODO #N`.

Last updated: 2026-10-12
Repo: https://github.com/debolai/gridpulse

## Current focus
- Phase A3 — dbt slice (local Trino target first; the `aws` target waits on TODO #6)

## Next up
1. A3: `transform/` dbt project with `dbt-trino` (local) and `dbt-athena` (aws) targets; `adapter.dispatch` macros for engine differences
2. A3: seed `ba_reference` (BA code, name, time zone, interconnection)
3. A3: `stg_eia__region_data` (cast, rename, dedupe by `_record_hash`) → `int_grid__latest_values` (incremental merge, `lookback_filter()`) → `dim_balancing_authority`, `fct_grid_hourly` with contract
4. A3: dbt unit tests incl. DST spring-forward/fall-back days; generic tests
5. Load ~3 months of sample data locally (`make extract-sample START=2026-07-01 END=2026-10-01`)

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
- [x] **A2 region-data extractor** — 2026-10-12 — done when a rerun adds no new distinct rows and the completeness assert passes
  - Evidence: `make extract-sample START=2026-10-01 END=2026-10-08` twice → 3,984/3,984 rows (completeness OK), same run_id; Trino: 7,968 raw rows, 3,984 distinct hashes = 3,984 distinct keys. `make test-integration` 2 passed (rerun test in a throwaway namespace, cleaned up). 31 unit tests on recorded fixtures.
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
