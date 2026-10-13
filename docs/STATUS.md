# GridPulse — Status

Single source of truth for what is done and what is next. Read at the start of every session; update before ending one.
A step is ticked only with the date and the evidence (command/output) that proved its "done when" check.
Human-only tasks live in the git-ignored `TODO.md` and are referenced here as `TODO #N`.

Last updated: 2026-10-12
Repo: https://github.com/debolai/gridpulse

## Current focus
- Phase B1 — Data coverage, in vertical slices: (1) fuel mix ✅, (2) interchange, (3) quality flags, (4) revision audit, (5) NOAA weather, (6) BA snapshot + ingestion-run facts. Done when all marts build, reconciliation passes on ≥ 98% of BA-hours, and `fct_data_revisions` shows real revisions. (Phase A closes when TODO #11 lands; see Next up.)

## Next up
1. B1 slice 2: interchange (`stg_eia__interchange_data`, `fct_interchange_hourly`, reconciliation of neighbour flows to TI, pair symmetry A→B = −(B→A))
2. B1 slices 3–6 (quality flags, revision audit, NOAA weather, snapshot + ingestion runs)
3. **When TODO #11 lands: revert the temporary OpenAI provider** (ADR-0003 revert checklist), rerun `make agent-eval` on Bedrock (then tick A5), the full `make aws-down && make aws-up` cycle (then tick A6), re-record the GIF, close the MVP checkpoint

## Blockers
- TODO #11 (AWS Support: Bedrock quota is 0 for every model family on this account) blocks the deployed assistant, the A6 smoke question, and the revert to the blueprint's Bedrock-only setup.

## Temporary deviations (revert when unblocked)
- ADR-0003: local agent runs on the OpenAI API (`GRIDPULSE_AGENT_PROVIDER=openai`) instead of Claude on Bedrock. Revert when `make bedrock-check` shows OK (TODO #11); checklist in the ADR.

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
- [x] **A3 dbt slice** — 2026-10-12 — done when `dbt build` passes on `local` and `aws` targets with equal row counts for a fixed window
  - [x] Local (Trino) half — 2026-10-12. Evidence: `make dbt-build` PASS=26 (1 seed, 4 models, 18 data tests, 3 unit tests incl. DST spring-forward/fall-back, Arizona and the A→B→A revert case). Incremental vs `--full-refresh` in a check schema: 14,832 = 14,832 rows, 0 differences either way. `make test-integration` 3 passed, no test schemas left.
  - [x] AWS (Athena) half — 2026-10-12. Evidence: Terraform foundation applied (27 resources; re-plan shows no changes). `make extract-sample-aws START=2026-07-01 END=2026-10-12` → 58,943/58,943 rows via Glue. `make dbt-build-aws` PASS=26. `fct_grid_hourly` 14,832 rows on both engines; July per-BA hours, demand, net generation, interchange, local dates and hour ranges IDENTICAL between Trino and Athena.
- [x] **A4 Semantic layer** — 2026-10-12 — done when `mf validate-configs` passes and every metric matches its reference SQL
  - Evidence: spike on both engines (ADR-0002): `mf validate-configs` 0 errors/0 warnings incl. warehouse checks on Trino and Athena; sum, ratio, cumulative and join queries IDENTICAL Trino vs Athena. `test_semantic_ground_truth.py` 9 passed (each metric = hand-written SQL, rel tol 1e-9; MTD at day boundaries; unknown-metric rejection; cache hit; agent allow-list). 12 request-contract unit tests.
  - Built: time spines (hourly/daily), `fct_grid_coverage_hourly`, metrics demand, peak_demand, forecast_error_mape, forecast_bias, data_completeness, demand_month_to_date; semantic API (`make semantic-api`, /health /metrics /compile /query, cache keyed by dbt invocation).
  - Later (A6): semantic API container image.
- [ ] **A5 Minimal agent** — done when eval accuracy ≥ 90% and an injected wrong number is caught
  - [x] Injected wrong number is caught — 2026-10-12. `test_ground_check.py` + `test_graph.py`: a wrong figure triggers one rewrite with feedback, a persistent one falls back to the raw table; computed (summed) numbers and wrong rounding are rejected.
  - [x] Offline build — 2026-10-12: LangGraph graph (route → plan → validate → execute → answer → ground-check, ≤2 replans on validator/API errors), provider switch (bedrock | anthropic | ollama), FastAPI `/ask` with optional bearer token, Streamlit UI, 17-case golden set + scorer, contract test against the semantic API. 30 agent unit tests (74 total) pass.
  - [ ] Eval accuracy ≥ 90% — **provisional pass on OpenAI, 2026-10-13** (ADR-0003): `make agent-eval` 16/17 (94%; the miss read "yesterday" as today), then 17/17 (100%) with GPT-6 Luna router + GPT-6.1 Sol planner. Live `/ask` "What was PJM total demand in July 2026?" → answered, 85,612,424 MWh, ground-check clean on the first attempt; equals the semantic API and the Athena smoke figure. Tick for good after the same eval passes on Bedrock (TODO #11).
- [ ] **A6 Scheduling + AWS** — done when `make aws-down && make aws-up` restores a demo that answers the smoke question
  - [x] A6a local scheduling — 2026-10-12. Airflow 3.3.2 (`make up-orch`, UI http://localhost:8088): `eia_hourly` (cron :15, catchup=False, eia_api pool, one extract at a time) publishes the raw_eia asset → `dbt_build` (asset-triggered dbt container) → semantic cache refresh. Evidence: from `make reset`, stack up in 19 s, triggered run succeeded, dbt_build asset-triggered and succeeded, marts populated (432 rows = 6 BAs × 72 h). Catch-up: watermark wound back to Oct 7 → one run loaded Oct 7 → Oct 12 (3,190 rows) and advanced the watermark. `make dag-check` OK.
  - [ ] A6b AWS demo deployment
    - [x] First `make aws-up` — 2026-10-12. EKS (2 arm64 Spot nodes), semantic API + agent API + UI images in ECR, Helm release; on the redeploy, Terraform had nothing to change and the deploy took ~1 min. Smoke: `PJM demand, July 2026: semantic API 85,612,424 vs Athena 85,612,424 -> MATCH`. The assistant returns 500 (Bedrock `ThrottlingException: Too many tokens per day`, TODO #11).
    - [x] `make aws-down` — 2026-10-13. Terraform: 58 destroyed. Verified directly: no EKS cluster, RDS instance, running EC2, Elastic IP or gridpulse VPC; the flagged NAT gateway is `deleted`, and the VPC endpoint and security group are `NotFound`.
    - [x] Clear errors instead of 500 — 2026-10-13. Model-provider failures (Bedrock ClientError codes, OpenAI/Anthropic status codes, connection errors) return 503 `model_throttled` / `model_access_denied` / `model_unreachable` with a plain message and `Retry-After`; an unreachable semantic API returns 503 `metrics_unavailable` (matched by URL); anything else stays 500. UI shows the message. 17 tests; live: throttled Bedrock → `503`, `retry-after: 60`, "The language model is rate-limited or out of quota right now."
    - [ ] A full `make aws-down && make aws-up` cycle answers the smoke question (needs TODO #11)
- [ ] **MVP checkpoint** — README MVP section, demo GIF, "still to come" list
  - [x] README MVP section (flow diagram, evidence table, temporary-OpenAI note) and "still to come" list — 2026-10-13
  - [x] Demo GIF — 2026-10-13. `make demo-gif` drives the local UI with Playwright 1.63.0 on the installed Chrome and stitches frames with Pillow → `docs/assets/demo.gif` (14 frames, 212 KB): typing, spinner, verified answer, chart, metric request. Recorded on the OpenAI provider; re-record after the Bedrock revert.
  - [ ] Closes with A5 and A6 (both wait on TODO #11 for their Bedrock runs)

## Phase B — Depth
- [ ] **B1 Data coverage** — done when all marts build, reconciliation passes on ≥ 98% of BA-hours, and `fct_data_revisions` shows real revisions from re-pulled windows
  - [x] Slice 1: fuel mix — 2026-10-13. Routes `fuel-type-data` and `interchange-data` in the extractor (row models, recorded multi-page fixtures, 10 new tests). Seed `fuel_type_map` (16 codes), `stg_eia__fuel_type_data`, `int_generation__latest_values`, `dim_fuel_type`, `fct_generation_by_fuel_hourly` (contract). Evidence: `make extract-sample ROUTE=fuel-type-data START=2026-07-01 END=2026-10-13` twice → 125,744/125,744 rows each, 125,744 distinct hashes (rerun idempotent). `make dbt-build` PASS=57 on Trino and `make dbt-build-aws` PASS=57 on Athena; July per-BA rows, generation and fuel counts IDENTICAL. Reconciliation (fuels sum to NG within 1% or 1 MWh) per BA: ERCO/MISO/NYIS 100%, CISO 99.39%, ISNE 99.15%, PJM 98.87%; the test fails as expected at 0.1% tolerance (2 BAs).
  - [ ] Slice 2: interchange
  - [ ] Slice 3: quality flags
  - [ ] Slice 4: revision audit (`int_grid__revisions`, `fct_data_revisions`)
  - [ ] Slice 5: NOAA weather
  - [ ] Slice 6: `snap_ba_reference`, `fct_ingestion_runs`
  - [ ] Elementary (data observability)
- [ ] B2 Orchestration on k3d (Airflow 3 Helm, KubernetesExecutor, Cosmos, 7 DAGs, pool, alerts) + full backfill on AWS
- [ ] B3 Full semantic layer (12 metrics, saved queries, allow-list, cache)
- [ ] B4 Full agent (clarify, inspect, checkpointer, 50-question golden set, nightly eval)
- [ ] B5 CI/CD (slim CI, local-target CI, Terraform plan comments, cd.yml with approval, rollback, pr-cleanup)
- [ ] B6 Polish (README, video, dbt docs, ADR index, cost report, data-issue write-up)
- [ ] B7 Optional (hosted dbt Semantic Layer demo, Cube comparison)

## Deferred / later
- (empty — park scope creep here instead of starting it)

## Findings to fold into the build
- 2026-10-12: The dbt manifest bakes in the target's catalog (`lake` vs `awsdatacatalog`). The semantic image parsed at build time with the default `local` target, so on EKS every query failed with `CATALOG_NOT_FOUND: Catalog 'lake'`. The entrypoint now re-parses for `DBT_TARGET`.
- 2026-10-13: EIA fuel codes come with inconsistent names (PS = "Pumped storage"/"Pumped Storage", BAT = "Battery"/"Battery storage", UES and SNB likewise), so `fuel_type_map` is keyed on the code and EIA's label is not used downstream. Codes are validated by shape at ingestion; an unknown code warns in dbt instead of failing.
- 2026-10-13: Fuel mix vs net generation: PJM's fuels run a steady ~0.4% (≈470 MWh/h) off its NG; CISO and ISNE have isolated hours off by up to 245% / 100% (partial fuel reports). Candidates for quality flags in slice 3.
- 2026-10-13: Fuel-type data lags region-data: the latest fuel hour was 06:00 UTC when region-data had 20:00.
- 2026-10-13: The UI showed time-series rows in arrival order when the planner omitted `order_by`; it now sorts by the time column (the chart already did).
- 2026-10-13: Editing an OpenAI key's permissions after creation left about half of all calls failing with 401 `missing_scope` for 15+ minutes; a fresh key created with the right scope worked at once (12/12). Restricted keys need only Model capabilities = Write (`model.request`); listing models needs `api.model.read`, so `make openai-check` makes one tiny call per model instead.
- 2026-10-13: gitleaks in a container fails open when it runs git itself (git errors, then "no leaks found", exit 0). The hook pipes `git diff --cached` into `gitleaks stdin` instead; verified it blocks a fake OpenAI key and passes clean changes. Full history is clean apart from the local stack's dummy SeaweedFS credentials (allowlisted in `.gitleaks.toml`).
- 2026-10-13: The tagging API keeps listing deleted NAT gateways, VPC endpoints and security groups long after they are gone, so `aws-down` reported 3 false leftovers. The check now confirms each flagged EC2 resource against EC2 itself; other types still count as present.
- 2026-10-13: The new account's Bedrock restriction is account-wide: Claude, OpenAI gpt-oss and Amazon Nova all fail with "Too many tokens per day", and OpenAI GPT-5.5/6.x are "not available for this account". Switching model families on Bedrock doesn't help; only TODO #11 or a direct API provider does.
- 2026-10-12: Lakekeeper remote signing caused intermittent "Access Denied" on Iceberg writes under concurrency; disabled for the local warehouse (clients write with their own S3 credentials, like IAM roles on AWS). Three concurrent writers then all succeeded.
- 2026-10-12: Airflow 3: manual runs have no data interval (`data_interval_end` is undefined, not None); DAGs anchor on `dag_run.run_after`. Marking a run failed doesn't stop a running task, so extracts set `max_active_tis_per_dag=1`.
- 2026-10-12: SeaweedFS reports healthy before its access keys load; the health check now makes a signed S3 request.
- 2026-10-12: MetricFlow gotchas (ADR-0002): time bounds snap to query grain (API uses typed half-open metric_time filters instead); cumulative `period_agg` defaults to `first`; partial parsing keeps stale metrics (`make semantic-manifest` does a full parse); dimensions are entity-scoped (`grid_hour__hour_local`).
- 2026-10-12: AWS SSO: boto3 can reject an SSO token the cache still lists as valid, while the CLI keeps working from cached role credentials. Workaround: `aws configure export-credentials`; fix: `aws sso login`.
- 2026-10-12: Athena casts a zoned timestamp to `timestamp` by converting to UTC (Trino keeps the wall clock). Local times would silently have equalled UTC; the DST unit test caught it. `athena__utc_to_local` formats then parses instead.
- 2026-10-12: Athena views live in the Glue/Hive catalog: no `timestamp(6)`. `timestamp_type()` dispatches the type; contracts choose it inline (YAML can't call macros). dbt unit tests on Athena use Hive CTAS, so models cast UTC timestamps explicitly.
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
- 2026-10-12 — A3 complete: AWS foundation applied (buckets, Glue, Athena workgroups, $50 budget); sample loaded via Glue; dbt builds on Athena with identical results to Trino. Next: A4 MetricFlow spike on both engines.
- 2026-10-12 — A4 complete: MetricFlow spike passed on Trino and Athena (ADR-0002); 6 governed metrics; semantic API with SQL ground-truth tests. Next: A5 agent.
- 2026-10-12 — A5 offline parts complete (graph, validator, ground-check, API, UI, golden set); live eval waits on the Bedrock use-case form (TODO #7). Next: A6 while waiting.
- 2026-10-12 — A6a complete: Airflow 3 local scheduling with asset-driven dbt and gap catch-up via the extractor watermark; fixed remote-signing write failures. Next: A6b AWS deployment (plan first).
- 2026-10-12 — A6b: first `make aws-up` deployed; smoke failed on a build-time dbt manifest for the wrong target (fixed: parse at container start); redeploy matches Athena exactly. Assistant still throttled by the Bedrock quota (TODO #11). 
- 2026-10-13 — A6b: `make aws-down` verified nothing billable left; fixed false leftovers in its check. Bedrock test showed the quota block covers every model family (TODO #11 updated). Next: pick a direct API provider or wait for #11.
- 2026-10-13 — Temporary OpenAI provider (local only, ADR-0003) with a Kubernetes guard and `make openai-check`; gitleaks added to pre-commit and CI. Waiting on TODO #12 (key) for the live eval; revert to Bedrock when #11 lands.
- 2026-10-13 — TODO #12 done (second key; the edited first key failed half its calls). A5 eval passes on OpenAI: 94% then 100%; live `/ask` answer matches the semantic API and Athena. Provisional until the Bedrock rerun (#11). Local stack stopped, caches cleaned.
- 2026-10-13 — Agent API returns 503 with a clear reason for model/metrics outages (live-checked on throttled Bedrock). README MVP section, flow diagram, evidence table and Phase B list; demo GIF recorded with `make demo-gif`. Local stack stopped. Next: commit + PR.
- 2026-10-13 — B1 started. Slice 1 (fuel mix) done on both engines: extractor routes for fuel-type and interchange, fuel seed, staging → latest values → `dim_fuel_type` + `fct_generation_by_fuel_hourly`, reconciliation test (≥ 98% per BA, all pass). Next: slice 2 (interchange).
