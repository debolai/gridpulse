# GridPulse: Grid Operations Analytics Platform — Blueprint

Oct 12, 2026 · @Debola

GridPulse turns hourly U.S. electricity grid data and weather into governed metrics that analysts and an LLM assistant can query without writing SQL. It is built as if for a grid analytics team at a utility, energy trader, or clean-energy developer.

## Project overview

**The problem.** Grid operators publish hourly demand, forecasts, generation by fuel, and interchange through EIA. The data is valuable but painful to use: past hours get revised, regions report in different time zones, values go missing or spike, and every analyst computes "forecast error" or "renewable share" slightly differently. GridPulse solves that with one tested pipeline and one set of metric definitions.

**Business questions the platform answers.**

- How accurate was each balancing authority's day-ahead demand forecast, and when does it miss?
- What share of generation came from wind, solar, and other renewables, by region and hour?
- How does temperature drive demand, and which regions are most weather-sensitive?
- Which regions are net importers at peak, and how has that changed?
- How fresh and complete is the data right now?

**Scope.** The project covers the Lower 48 balancing authorities over the last year (from 2025-10-01; ADR-0005) to the present, refreshed hourly. EIA-930 history goes back to July 2018 and can be added later with the same backfill command. Out of scope: real-time trading signals, price data, and sub-hourly data.

**What it demonstrates.**

| Skill area | Evidence in the repo |
| --- | --- |
| Data ingestion | Paginated, idempotent API extractors with revision handling and backfills |
| Data lake | S3 raw/staged/curated zones with Apache Iceberg tables queried through Athena |
| Data modeling | dbt layers (staging, intermediate, marts), incremental models, contracts, snapshots |
| Semantic modeling | dbt semantic models and MetricFlow metrics, served by a self-hosted semantic API (Cube as a comparison track) |
| LLM application | LangGraph agent that answers questions only through governed metrics |
| Orchestration | Airflow DAGs with data-aware scheduling, backfills, and freshness SLAs |
| DevOps | Terraform, Docker, Kubernetes (EKS), GitHub Actions CI/CD, branch strategy |
| Testing and validation | Unit, data, contract, integration, and LLM evaluation tests gated in CI |

Every stack choice and implementation below carries a **Decision** and **Why** so reviewers see the reasoning, not just the tools.

## Data sources

Three free sources feed the platform: EIA grid data (the core), NOAA weather (the driver), and small hand-built reference tables (the glue). All are U.S. government public data with no personal information.

| Source | What it provides | Access | Refresh | Volume (approx.) |
| --- | --- | --- | --- | --- |
| [EIA API v2](https://www.eia.gov/opendata/documentation.php) `electricity/rto/region-data` | Hourly demand (D), day-ahead demand forecast (DF), net generation (NG), total interchange (TI) per balancing authority | Free API key, JSON | Hourly, with revisions to past hours | \~65 BAs × 4 series × 8,760 h ≈ 2.3M rows/year |
| EIA `electricity/rto/fuel-type-data` | Hourly generation by fuel (coal, gas, nuclear, wind, solar, hydro, other) per BA | Same key | Hourly | \~5M rows/year |
| EIA `electricity/rto/interchange-data` | Hourly flows between neighboring BAs | Same key | Hourly | \~1.5M rows/year |
| NOAA GHCNh (Global Historical Climatology Network hourly) on the AWS Open Data Registry (replaced ISD, ADR-0004) | Hourly temperature, dew point, wind at airport stations | Public S3 bucket `noaa-ghcnh-pds`, no key | Daily, about 1.5 days behind | Filtered to \~150 stations |
| Reference seeds (built in repo) | BA codes, names, time zones, interconnection; BA-to-weather-station mapping with population weights | dbt seeds (CSV) | Manual, versioned in Git | < 1,000 rows |

**Decision (revised 2026-10-13, ADR-0005): load one year of history, from 2025-10-01.** Why: the app needs no more to answer its questions, and one year loads in under an hour instead of several, without first rewriting the full-rebuild models. A common start date still keeps every metric comparable. The original start, July 2018 (when generation by fuel type begins), stays available as an optional extension.

**Decision: use NOAA from the AWS Open Data Registry rather than a weather API.** Why: it sits in AWS already, so reads are fast and free of rate limits, it is public domain, and it shows you can work with a large partitioned public dataset. Open-Meteo is the fallback if station coverage is thin.

**Decision: build the BA-to-weather mapping as a versioned seed.** Why: no official mapping exists. Picking two to four large cities per BA and weighting by population is a defensible, documented modeling choice, and reviewers can see and challenge it.

**Known data quirks (these are the real-world pain points the project solves):**

- **5,000-row cap per call.** The API returns at most 5,000 JSON rows and reports the total, so extractors must paginate with `offset` and `length`.
- **Values arrive as strings.** Since API v2.1.6 (January 2024), all data values are returned as strings, so staging models must cast and validate types.
- **Revisions.** Operators correct past hours days or weeks later, so a naive "load only new hours" pipeline silently goes stale.
- **Two time conventions.** The API offers UTC hourly and local hourly frequencies, and BAs span four time zones plus DST. The platform stores UTC and derives local time from the seed.
- **Gaps, zeros, and spikes.** Some BAs report missing hours, zero demand, or implausible spikes. These are flagged, not silently dropped.
- **Sign conventions.** Interchange is positive for exports and negative for imports, which must be documented in the semantic layer so the LLM does not invert it.
- **API throttling.** EIA temporarily suspends keys that exceed request limits, so the extractor rate-limits itself and retries with backoff.
- **Aggregate respondents.** Without a BA filter the API also returns EIA's 13 regional sums and US48 as if they were respondents. Pooled with BAs they count every MWh about three times, so staging drops them (seed `eia_aggregate_respondents`); raw keeps them.

**Licensing.** EIA data is free and governed by EIA's [copyright and reuse policy](https://www.eia.gov/about/copyrights_reuse.php) and [API terms of service](https://www.eia.gov/opendata/terms-of-service.php); NOAA data is public domain. Credit both in the README.

## Architecture overview

Data moves in one direction, from the EIA and NOAA sources through an Iceberg lake and dbt models into a semantic layer, and the LLM agent reads only from that semantic layer.

&#91;embedded content: GridPulse architecture · sources to serving\]

The highlighted box is the control point: analysts, dashboards, and the agent all get numbers from the same dbt metric definitions, so every consumer computes "renewable share" or "forecast error" the same way.

## Local and cloud runtime

The platform runs fully offline on a laptop and on AWS from the same code, and the AWS compute can be destroyed and recreated with one command.

| Piece | Local (`local` target) | AWS (`aws` target) |
| --- | --- | --- |
| Object storage | SeaweedFS (S3-compatible; see ADR-0001) | Amazon S3 |
| Iceberg catalog | Lakekeeper (Iceberg REST, Postgres-backed) | AWS Glue Data Catalog |
| Query engine | Trino | Amazon Athena v3 (Trino-based) |
| dbt adapter | `dbt-trino` | `dbt-athena` |
| Compute | Docker Compose, then `k3d` | Amazon EKS |
| Postgres | Container | RDS |
| LLM | Claude on Bedrock via local AWS credentials | Claude on Bedrock via Pod Identity |

**Decision: fully offline local mode on Trino.** Local object storage is SeaweedFS, because MinIO no longer publishes community images (ADR-0001). Why: reviewers can run `make up` with no AWS account, CI can test dbt and the semantic layer for free in service containers, and the dev loop avoids Athena's per-query startup time. Athena v3 is built on Trino, so SQL carries over; the few differences (merge and table properties, `OPTIMIZE`/`VACUUM`) live in `adapter.dispatch` macros. MetricFlow officially supports Trino, so this also serves as the ready fallback for the Athena-compatibility risk. Trade-off: two dbt targets to keep in step, so CI also builds against Athena.

**Decision: split Terraform into a persistent foundation and ephemeral compute.** Why: the foundation (state bucket, lake buckets, Glue, Athena workgroups, ECR, IAM, GitHub OIDC, SSM, budgets) costs a few dollars a month and holds the data, so it stays up. Compute (VPC with NAT, EKS, Spot nodes, RDS, Helm releases) is created by `make aws-up` (about 20–25 minutes, restoring RDS from its latest snapshot, then running the smoke test) and removed by `make aws-down` (final RDS snapshot, destroy, then a tagging-API check that fails if any `gridpulse:ephemeral` resource remains).

**Decision: protect the laptop's memory and disk.** Why: the full local stack wants 8–10 GB. Compose profiles start only what a task needs (`make up-lake` ≈ 3 GB, `up-orch` +3 GB, `up-app` +1.5 GB), every service has a memory limit (Trino heap capped at 2 GB), and local data is a sample of about six BAs × three months. Tests create `test_<run_id>` schemas and drop them in teardown even on failure. `make down`, `clean`, `reset`, `prune` and `doctor` stop, tidy, wipe, reclaim and check, from lightest to heaviest.

## Stack decisions

The stack favors serverless, pay-per-use AWS services and open-source tools, so the whole platform runs for well under $50/month outside demo windows. Each row is one decision; the deeper reasoning lives in the section for that layer.

| Layer | Choice | Why | Rejected alternative (and why) |
| --- | --- | --- | --- |
| Language and tooling | Python 3.12, `uv`, `ruff`, `pre-commit` | `uv` gives fast, locked, reproducible installs; `ruff` replaces several linters with one | Poetry: slower and adds little here |
| Ingestion | Custom Python extractors (`httpx`, `tenacity`, `pydantic`) in a container | The EIA API needs revision windows, pagination, and throttling that off-the-shelf connectors do not handle well; writing it shows engineering depth | Airbyte or Fivetran: heavy to run or paid, and hides the interesting logic |
| Storage | Amazon S3 with raw, staged, and curated zones | Cheap, durable, the standard AWS lake foundation | — |
| Table format | Apache Iceberg, AWS Glue Data Catalog | ACID `MERGE` handles revised hours cleanly; time travel lets you audit what a number was before a revision; schema evolution is safe | Plain Parquet + Hive partitions: revisions force full partition rewrites and there is no audit trail |
| Query engine | Amazon Athena (engine v3) | Serverless, pay per TB scanned, native Iceberg `MERGE` support | Redshift Serverless or Snowflake: better performance, but idle cost or trial limits make them poor fits for a portfolio |
| Transformation | dbt Core + `dbt-athena` adapter | Industry standard for analytics engineering; incremental Iceberg models, tests, contracts, docs | SQL scripts in Airflow: no lineage, testing, or docs |
| Semantic layer | dbt semantic models and metrics (MetricFlow), served by a self-hosted API; Cube as an optional comparison | The dbt Semantic Layer is the semantic-layer skill most analytics engineering job descriptions ask for; open-source MetricFlow is Apache 2.0 and runs wherever a dbt adapter does | Hosted dbt Semantic Layer as the main path: needs a paid dbt plan and does not support Athena, so it is kept as an optional demo. Cube as the main path: works well, but metrics would live outside dbt |
| LLM app | LangGraph agent, Claude via Amazon Bedrock, FastAPI service, Streamlit UI | LangGraph gives explicit, testable control flow; Bedrock keeps auth inside AWS IAM with no API keys to leak | A single prompt with free-form text-to-SQL: unpredictable and hard to test |
| Orchestration | Apache Airflow 3 on Kubernetes (official Helm chart), Astronomer Cosmos for dbt | Data-aware scheduling, backfills, and SLAs; Cosmos turns each dbt model into an Airflow task with its own retries | Amazon MWAA: always-on environment costs hundreds per month; Dagster: great tool, but Airflow is what most job postings ask for |
| Containers | Docker, Amazon ECR | One image per component, same image from laptop to cluster | — |
| Kubernetes | `k3d` locally; Amazon EKS for demos | `k3d` gives a real cluster for free during development; EKS proves cloud deployment | EKS running 24/7: the control plane alone costs about $73/month |
| Infrastructure as code | Terraform with S3 remote state and native S3 locking | Most widely used IaC tool; `plan` output in pull requests makes changes reviewable | AWS CDK: AWS-only and less common in data teams |
| CI/CD | GitHub Actions with OIDC into AWS | No long-lived AWS keys in GitHub; free minutes for public repos | Jenkins: extra infrastructure to run |
| Secrets | AWS SSM Parameter Store + External Secrets Operator | Standard parameters are free; secrets sync into Kubernetes without being committed | Kubernetes Secrets in Git: insecure |
| Data quality | `pydantic` at ingestion, dbt tests and unit tests, `dbt-expectations`, Elementary (open source) | Catches bad data at each layer and reports anomalies over time | Great Expectations: overlaps heavily with dbt tests here and adds setup |

**Decision: pin every version.** Why: Airflow, LangGraph, and the dbt adapters change fast. Lock Python packages with `uv.lock`, Helm charts by chart version, Terraform providers in `.terraform.lock.hcl`, and container images by tag plus digest. Record the pinned set in the repo's spec file so a coding assistant uses the same APIs.

## Ingestion layer

Ingestion re-pulls a rolling window of recent hours on every run and keeps every version it sees, so revised values are captured and nothing is ever overwritten at the source layer.

**How a run works.**

1. Airflow passes a route (`region-data`, `fuel-type-data`, `interchange-data`) and a time window to the extractor container.
2. The extractor requests `frequency=hourly` (UTC), sorts explicitly by `period`, `respondent`, then `type` (or the route's equivalent, so the order is total), and pages with `offset` and `length=5000` until it has collected the `total` the API reports.
3. Each page is validated with a `pydantic` model, then the raw JSON response is written untouched to S3.
4. Validated rows, plus `_ingested_at`, `_run_id`, and a `_record_hash` of the business fields, are appended to an Iceberg raw table with PyIceberg.
5. The run writes a small manifest (rows expected, rows received, pages, duration) that later tests read.

**Decision: rolling lookback windows instead of "new hours only."** Why: the API has no "last updated" field, so the only way to catch revisions is to re-read recent history. Hourly runs pull the last 72 hours; a daily run pulls the last 30 days. Why those numbers: most corrections land within days, and the 30-day sweep catches late ones at low cost. Make both values configurable and measure them (see revision audit below).

**Decision: append-only raw history, deduplicated later in dbt.** Why: keeping every version of every hour makes the pipeline replayable and enables a revision audit (how often and how much each BA revises its numbers), which is a genuinely useful data-quality product. Storage is cheap; lost history is not recoverable.

**Decision: keep the raw JSON response in S3 as well as the Iceberg rows.** Why: if parsing logic has a bug, you can reprocess from the original response without calling the API again.

**Decision: explicit sort on every paged request.** Why: paging without a fixed order can skip or repeat rows between pages. EIA added a default sort in 2025, but an explicit sort makes the extractor correct regardless of API defaults.

**Decision: assert row completeness per run.** Why: the API reports a `total` for each query. If collected rows do not equal `total`, the task fails loudly instead of loading a partial window.

**Decision: self-imposed rate limit plus exponential backoff with jitter.** Why: EIA temporarily suspends keys that exceed its throttles. A token-bucket limiter (default about one request per second, configurable) and `tenacity` retries on 429 and 5xx responses keep backfills from locking you out.

**Decision: deterministic, idempotent runs.** Why: `_run_id` is derived from route plus window, and raw S3 keys use it, so re-running a window overwrites the same raw files and produces the same hashes. Raw keeps every load; the latest-value model picks the newest observation per key, so reruns change nothing downstream. Run manifests are kept per attempt, so a failed attempt stays on record after a successful retry.

**Decision: schema drift policy.** Why: unknown new fields are logged and stored in a JSON overflow column, so the run continues; a missing required field fails the run. This mirrors how production teams treat additive versus breaking changes.

**Weather ingestion (revised 2026-10-13, ADR-0004).** A daily task reads the NOAA GHCNh Parquet files (one per station and year) for the mapped stations directly from the public S3 bucket. GHCNh replaced ISD, which stopped updating in August 2025. Values are already in °C and m/s with nulls for missing readings; stations report several times an hour, and every report is kept. Quality codes follow NOAA's GHCNh documentation (lower-case letters = failed GHCNh checks; legacy 2/6 suspect, 3/7 erroneous); failing readings are kept but flagged and not used.

**S3 raw layout.**

```
s3://gridpulse-<env>-raw/
  eia/route=region-data/ingest_date=2026-10-12/run_id=<hash>/page=0001.json.gz
  eia/route=fuel-type-data/...
  _manifests/run_id=<hash>.json
```

## Data lake layout

The lake has three zones in separate S3 buckets, each mapped to its own Glue database, with every table after raw stored as Iceberg and partitioned by month.

| Zone | S3 bucket | Glue databases | Written by | Contents |
| --- | --- | --- | --- | --- |
| Raw | `gridpulse-<env>-raw` | `raw` | Extractors (PyIceberg) | Original API responses and append-only raw Iceberg tables |
| Staged | `gridpulse-<env>-lake` | `staging`, `intermediate` | dbt | Typed, deduplicated, conformed models |
| Curated | `gridpulse-<env>-lake` | `marts`, `snapshots` | dbt | Facts, dimensions, and audit tables read by the semantic layer and analysts |
| Ops | `gridpulse-<env>-athena-results` | — | Athena | Query results, expired after 7 days |

**Decision: Iceberg hidden partitioning by `month(period_utc)` for fact tables.** Why: daily partitions would hold only about 15,000 rows each, creating thousands of tiny files that slow Athena down. Monthly partitions keep files reasonably sized, and Iceberg prunes on any time filter without users needing to know the partition column.

**Decision: scheduled compaction and snapshot expiry.** Why: frequent `MERGE` operations from revisions create small files and many snapshots. A weekly Airflow task runs Athena `OPTIMIZE ... REWRITE DATA USING BIN_PACK` and `VACUUM` to keep queries fast and storage bounded, while retaining 30 days of snapshots for time travel.

**Decision: separate dev and prod buckets and Glue databases, plus ephemeral CI schemas.** Why: dbt in CI builds into `ci_pr_<number>` databases that are dropped when the pull request closes, so tests never touch production data. This mirrors real team setups.

**Decision: Athena workgroups with a per-query scan limit.** Why: a bad query or an LLM-generated query cannot run up a bill. The prod workgroup cancels any query scanning more than a set limit (start at 1 GB), and the agent's workgroup has a lower limit.

**Decision: security defaults on every bucket.** Why: Block Public Access, SSE-S3 encryption, TLS-only bucket policies, and versioning on the raw bucket are cheap and are what reviewers look for in Terraform. Lifecycle rules move raw JSON older than 90 days to S3 Intelligent-Tiering.

**Decision: IAM roles per workload, not AWS Lake Formation.** Why: Lake Formation adds a second permission system that is overkill for one team. Each workload (extractor, dbt, semantic API, agent) gets its own IAM role through EKS Pod Identity, scoped to the buckets and databases it needs. The agent's role is read-only on `marts`.

## dbt modeling

The dbt project follows the staging, intermediate, marts pattern, resolves revisions with incremental `MERGE` over a lookback window, and enforces contracts on every mart the semantic layer reads.

**Model inventory.**

| Layer | Model | Grain | Purpose |
| --- | --- | --- | --- |
| Seeds | `ba_reference` | One row per BA | Code, name, time zone, interconnection, active dates |
| Seeds | `ba_weather_stations` | BA × station | Station mapping and population weights |
| Seeds | `fuel_type_map` | One row per EIA fuel code | Maps codes to fuel names and a renewable flag |
| Staging | `stg_eia__region_data` | BA × series × hour × version | Cast strings to numbers, rename, drop exact duplicates (same `_record_hash` and same load). Loads are not collapsed by hash, so a value that reverts (A → B → A) still resolves to the newest load |
| Staging | `stg_eia__fuel_type_data` | BA × fuel × hour × version | Same pattern |
| Staging | `stg_eia__interchange_data` | BA pair × hour × version | Same pattern |
| Staging | `stg_noaa__observations` | Station × observation time × report type | Latest load per report, QC verdict from GHCNh quality codes |
| Intermediate | `int_grid__latest_values` | BA × series × hour | Latest version of each value; the revision-resolving model |
| Intermediate | `int_grid__revisions` | BA × series × hour × version | Each change between versions, with size and lag |
| Intermediate | `int_weather__station_hourly` | Station × hour | Mean of QC-passed reports; gaps of 2 hours or less interpolated and flagged |
| Intermediate | `int_weather__ba_hourly` | BA × hour | Population-weighted temperature with weight coverage |
| Intermediate | `int_grid__quality_flags` | BA × series × hour | Flags for missing, zero, negative, and spike values |
| Marts | `dim_balancing_authority` | One row per BA | Current attributes, built from the snapshot below |
| Marts | `dim_fuel_type` | One row per fuel | Fuel name, category, renewable flag |
| Marts | `fct_grid_hourly` | BA × hour | Demand, forecast, net generation, interchange, temperature, quality flags, UTC and local time |
| Marts | `fct_generation_by_fuel_hourly` | BA × fuel × hour | Generation by fuel |
| Marts | `fct_interchange_hourly` | BA × neighbor BA × hour | Directional flows |
| Marts | `fct_data_revisions` | Revision event | Audit of what changed, when, and by how much, across all three EIA routes |
| Marts | `fct_ingestion_runs` | Pipeline run | Expected versus received rows and run duration, from manifests (each run also appends its manifest to `raw.ingestion_runs`) |
| Snapshots | `snap_ba_reference` | BA × validity range | SCD Type 2 history of BA attributes |

**Decision (revised 2026-10-12): resolve revisions with `merge` on a unique key, driven by an ingestion watermark.** Why: each incremental run reads only observations loaded since the last run (`ingested_at_utc` above the model's own maximum, via the `incremental_watermark()` macro), whatever hours they cover, then merges on (`ba_code`, `series_code`, `period_utc`). Following the data rather than a fixed 30-day window means backfills and gap catch-ups older than the window still land, and dbt can never disagree with ingestion about what is new. `fct_grid_hourly` rebuilds only the BA-hours that changed. Partition-pruned merge predicates are deferred until Athena scan costs show they are needed. A monthly full refresh in a scheduled job proves the incremental logic matches a full rebuild (first proven locally on 2026-10-12: identical row sets).

**Decision: keep the revision history as its own mart.** Why: "how much does PJM revise its demand data, and how late?" is a real question data consumers ask. It also gives the LLM a way to warn that recent hours may still change.

**Decision: store UTC as the key and derive local time from the seed.** Why: UTC never repeats or skips an hour, so it is safe for joins and uniqueness. Local time, local date, and peak-hour flags are derived per BA using its time zone, which handles DST correctly. Unit tests cover the spring-forward and fall-back days.

**Decision: SCD Type 2 snapshot on BA reference data.** Why: balancing authorities occasionally retire, merge, or change names. A snapshot lets historical facts join to the attributes that were true at the time.

**Decision (2026-10-13, severity revised by ADR-0006): reconciliation checks with a pass rate and documented exceptions, reported as warnings.** Why: two EIA routes measure the same thing (fuel mix vs net generation, neighbour flows vs total interchange), so their agreement is a strong data-quality signal, but a few hours legitimately miss. Each check passes per BA when at least 98% of its hours agree within 1% (or 1 MWh); both numbers are dbt vars. A BA whose source data fails a check for a known reason (PJM's interchange) is listed in seed `reconciliation_exceptions` with the measured reason, instead of loosening the tolerance for everyone. Pair symmetry (A→B = −(B→A)) is not tested: neighbours meter and report differently. Across every BA for a year, 9 of 63 BAs miss the fuel-mix pass rate and 21 the interchange one for source-side reasons, so both checks warn by default (var `reconciliation_severity`) instead of failing the build.

**Decision: flag bad values instead of deleting them.** Why: deleting spikes hides problems from consumers and breaks totals silently. `int_grid__quality_flags` carries `is_missing`, `is_zero`, `is_negative`, `is_spike` per BA, series and hour, and `fct_grid_hourly` carries a `quality_status` per series (ok, suspect, invalid, missing; revised 2026-10-13: one status per series, because a single row-level status would mix a missing forecast with invalid demand). A spike is a one-hour outlier against both adjacent hours (threshold a dbt var). Metrics in the semantic layer exclude flagged rows by default and say so.

**Decision: enforce model contracts on all marts.** Why: MetricFlow semantic models and the agent depend on exact column names and types. A contract makes dbt fail the build if a change would break them, which is how you protect downstream consumers in a real team.

**Decision: declare the semantic API and the agent as dbt exposures.** Why: lineage in dbt docs then shows which marts feed the LLM, so anyone changing a model sees who depends on it.

**Conventions.** Model prefixes `stg_`, `int_`, `dim_`, `fct_`, `snap_`; snake\_case columns; units in column names (`demand_mwh`, `temperature_c`); timestamps suffixed `_utc` or `_local`; every model documented in YAML with a description on every column of every mart. SQL is linted with `sqlfluff` using the Athena dialect.

## Semantic layer

Metrics are defined once in the dbt project as semantic models and MetricFlow metrics (the same YAML the hosted dbt Semantic Layer reads), and the LLM agent can only request these metrics, never raw tables.

**Core metrics.**

| Metric | Definition | Unit | Notes for correct use |
| --- | --- | --- | --- |
| `demand` | Sum of hourly demand | MWh | Excludes rows flagged missing or spike |
| `peak_demand` | Maximum of hourly demand for one BA | MW | Not additive across BAs |
| `coincident_peak_demand` | Maximum over hours of demand summed across selected BAs | MW | The correct "system peak" for a region |
| `forecast_error_mape` | Mean of absolute(actual − forecast) ÷ actual | % | Only hours where actual > 0 and both values pass quality checks |
| `forecast_bias` | Mean of (forecast − actual) | MWh | Positive means the operator over-forecast |
| `net_generation` | Sum of net generation | MWh |  |
| `generation_by_fuel` | Sum of generation, by fuel dimension | MWh |  |
| `renewable_share` | Sum of renewable generation ÷ sum of all generation | % | Ratio of sums, never an average of ratios |
| `net_imports` | −1 × sum of total interchange | MWh | EIA reports exports as positive; this flips the sign so imports read positive |
| `cooling_degree_hours` | Sum of max(temperature − 18.3, 0) | °C·h | Base 18.3 °C (65 °F), the U.S. convention |
| `data_completeness` | Hours with valid values ÷ expected hours | % | Expected hours come from a generated hour spine |
| `revision_rate` | Hours revised at least once ÷ hours published | % | From `fct_data_revisions` |

**Dimensions.** Balancing authority, interconnection (Eastern, Western, ERCOT), fuel type, renewable flag, UTC hour, local hour, local date, month, peak-hour flag, and quality status.

**Decision: define ratio metrics as ratios of sums.** Why: averaging hourly renewable shares gives a different (wrong) answer than dividing total renewable generation by total generation. This is the most common metric bug in analytics, and the semantic layer makes it impossible to get wrong.

**Decision: separate `peak_demand` and `coincident_peak_demand`.** Why: adding each BA's own peak overstates the system peak because BAs peak at different hours. Two named metrics with clear descriptions stop analysts and the LLM from mixing them up.

**Decision: expose an allow-list of metrics and saved queries to the agent.** Why: the agent sees only metrics tagged `agent: true` in their `meta` config, plus a few saved queries for common questions. Fewer choices mean fewer wrong ones, and the allow-list is reviewed in pull requests like any other code.

**Decision: write descriptions and synonyms for the LLM in each metric's `description` and `meta`.** Why: the agent discovers metrics through the semantic API's catalog endpoint, which is built from dbt's semantic manifest. Descriptions such as "use this for regional system peak" and synonyms such as "load" for demand are what make natural-language questions map to the right metric.

**Decision: use the current dbt semantic YAML spec, with each semantic model declared inside its model's YAML.** Why: from dbt v1.12, semantic models live alongside the model they describe, and simple metrics replace the older "measures" concept. Learning the current spec is what job descriptions ask for, and it keeps documentation in one place. Install dbt and MetricFlow together through the `dbt-metricflow` bundle so their versions stay compatible. If the `dbt-athena` adapter lags behind v1.12, use the earlier spec (separate `semantic_models` with measures); the concepts are the same.

**Decision: cache results in the semantic API and turn on Athena query result reuse.** Why: most questions repeat over days and weeks. The API caches results keyed by the compiled SQL and the latest dbt run ID, so a cache entry expires exactly when new data lands, and Athena's result reuse avoids re-scanning for identical queries.

**Decision: default filters for data quality.** Why: every metric excludes flagged rows unless the query explicitly asks for them, and the agent always reports the completeness of the data behind an answer.

**Decision: serve metrics through a small self-hosted semantic API that wraps open-source MetricFlow.** Why: the hosted dbt Semantic Layer APIs need a paid dbt platform plan (or a time-limited trial) and do not list Athena among supported platforms. MetricFlow itself is Apache 2.0 licensed and works as a Python library that compiles metric requests into SQL using a dbt project and adapter. A FastAPI service with three endpoints (`GET /metrics`, `POST /compile`, `POST /query`) gives the agent the same contract the hosted API would, and building it shows you understand what a semantic layer does under the hood.

**Decision: prove the query engine in a one-day spike before building on it.** Why: MetricFlow renders engine-specific SQL, and Athena support through the `dbt-athena` adapter is not confirmed in dbt's own documentation. Phase 5 starts by compiling and running three metrics (a simple sum, a ratio, and a cumulative) on Athena. If that fails, add Trino on EKS as the serving engine. Trino is officially supported by both MetricFlow and the hosted Semantic Layer, and it reads the same Iceberg tables through the Glue catalog, so no data moves.

**Optional: a hosted dbt Semantic Layer demo.** Why: to show the hosted experience that job descriptions mention (the GraphQL and JDBC APIs, BI integrations, and the dbt MCP server), connect a dbt platform trial to a Trino-based engine, such as Starburst Galaxy, reading the same Iceberg tables. The metric YAML does not change; only the serving path differs. Run it for a demo window and record a short video, since trials expire.

**Cube learning track (optional, after Phase 6).** Rebuild four core metrics in Cube Core on the same marts, and add parity tests that compare Cube's results with MetricFlow's for a fixed day. Write an ADR comparing the two on modeling style, caching, APIs, and operations. Cube stays out of the production path so there is only one source of metric truth; the comparison itself is the portfolio piece.

## LLM application

The GridPulse assistant is a LangGraph agent that turns a question into a structured metric request, validates it in code, runs it through the semantic API, and answers only with numbers that came back from it.

**Graph nodes, in order.**

1. **Route.** Classify the question as a metric question, a definition question ("what does renewable share include?"), or out of scope. Definition questions are answered from the metric catalog without running a query.
2. **Plan.** Using the metric catalog from the semantic API, produce a metric request (metrics, group-by dimensions, filters, time range, grain), the same shape as a MetricFlow query, as structured output validated by a `pydantic` schema.
3. **Validate.** Deterministic Python checks: every metric and dimension is on the allow-list, the time range is within limits, the row limit is set, and known traps are blocked (for example, summing `peak_demand` across BAs). On failure, the error goes back to Plan, with at most two retries.
4. **Clarify (when needed).** If the question is ambiguous, such as "California" (which spans several BAs) or "last week" with no time zone, the graph pauses with a LangGraph interrupt and asks the user one question.
5. **Execute.** Send the validated request to the semantic API, which compiles it with MetricFlow and runs it on the query engine.
6. **Inspect.** Check for empty results, low data completeness, and hours still inside the revision window.
7. **Answer.** Write the response from the result set, name the metric definitions used, state data freshness, and add caveats from the Inspect step. The UI shows the answer, a chart, the metric request, and the compiled SQL.
8. **Ground-check.** Before returning, extract every number in the answer and confirm it matches a value in the result (allowing for rounding). If not, regenerate once, then fall back to a plain table of results.

**Decision: the agent writes metric requests, never SQL.** Why: free-form text-to-SQL can join the wrong tables, average ratios, or scan the whole lake. A metric request can only combine governed metrics and dimensions, and MetricFlow decides how to compute them, so the semantic layer, not the model, owns the math.

**Decision: validation in code, not in the prompt.** Why: prompts are suggestions; code is a guarantee. Validation rules are plain Python with unit tests, so a reviewer can see exactly what the agent is prevented from doing.

**Decision: LangGraph over a single prompt or a generic agent loop.** Why: explicit nodes and edges make the flow testable node by node, support retries and human-in-the-loop pauses, and keep conversation state in a checkpointer so follow-up questions ("now compare that to last year") work.

**Decision: Claude on Amazon Bedrock, two model sizes.** Why: Bedrock authenticates through the pod's IAM role, so no API key exists to leak. A small, fast model handles routing and a larger model handles planning and answers, which cuts cost. Model IDs live in config and are pinned. *Temporary exception (ADR-0003): while this new account's Bedrock quota is 0, local development uses the OpenAI API with a budget-capped key in `.env`; key-based providers refuse to run in Kubernetes, and the exception is reverted once Bedrock works.*

**Decision: numeric ground-check on every answer.** Why: the main risk in an analytics assistant is a confident wrong number. Checking that every number appears in the query result catches hallucinated or miscalculated figures before the user sees them.

**Decision: Postgres checkpointer on the same database instance as Airflow's metadata, in a separate database.** Why: LangGraph needs persistent state for multi-turn conversations, and reusing the instance avoids another monthly cost.

**Serving.** A FastAPI service exposes `POST /ask` (with streaming) and `GET /health`. A Streamlit app is the demo UI. Both run as Deployments on Kubernetes, behind one ingress, with simple token auth for the demo.

**Evaluation.** A golden set of about 50 questions, each paired with the expected metric request, lives in `agent/evals/`. Scoring compares the planned request's metrics, group-by dimensions, filters, and time range to the expected query, which is deterministic and cheap. A pull request that touches `agent/` or `semantic/` must keep the pass rate at or above 90%. A nightly job runs the full graph end to end against the live semantic API and records answer accuracy and ground-check failures.

## Orchestration

Airflow 3 runs seven DAGs on Kubernetes; ingestion DAGs publish Airflow Assets, and the dbt DAG runs when those assets update rather than on a fixed clock.

| DAG | Schedule | What it does |
| --- | --- | --- |
| `eia_hourly` | Hourly at :15 | Extracts the three EIA routes in parallel for a 72-hour window ending at the run's data interval; publishes the `raw_eia` asset |
| `eia_daily_sweep` | Daily 04:00 UTC | Same extractors with a 30-day window to catch late revisions |
| `noaa_daily` | Daily 06:00 UTC | Loads the previous day's weather observations; publishes `raw_noaa` |
| `dbt_build` | On `raw_eia` or `raw_noaa` update | Source freshness check, `dbt build` through Cosmos, semantic API cache refresh, Elementary report |
| `lake_maintenance` | Weekly, Sunday | Iceberg `OPTIMIZE` and `VACUUM` on raw and mart tables |
| `dbt_full_refresh_check` | Monthly | Rebuilds marts in a scratch database and compares them to production to prove incremental logic is correct (rows older than the 30-day revision window + 2 days, which ingestion can no longer change) |
| `agent_eval_nightly` | Daily 07:00 UTC | Runs the full agent evaluation against the live semantic API and stores scores |

**Decision: anchor every extraction window to the run's data interval, not to "now."** Why: a run for 10:00 always pulls the same 72 hours whether it runs on time or a month later. That makes reruns reproducible and lets Airflow's built-in backfill rebuild any historical range correctly.

**Decision: asset-driven scheduling for dbt.** Why: dbt runs only when new raw data has actually landed, instead of on a guessed schedule that might run before ingestion finishes or after nothing changed.

**Decision: an Airflow pool named `eia_api` with 2 slots.** Why: during a backfill, dozens of extraction tasks could otherwise hit the API at once and get the key suspended. The pool caps concurrency across all DAGs, together with the extractor's own rate limiter.

**Decision: KubernetesExecutor, with extractors and dbt running in their own images.** Why: each task runs in its own pod, so a heavy backfill cannot starve other work. Extractors run through the KubernetesPodOperator and dbt through Cosmos's Kubernetes mode, so the Airflow image does not carry their dependencies and each component is versioned and deployed independently.

**Decision: Cosmos renders each dbt model as an Airflow task.** Why: a failed model retries alone instead of rerunning the whole project, and the Airflow graph shows dbt lineage, which helps when debugging at 3 a.m.

**Decision: freshness enforced by checks and alerts, not Airflow SLAs.** Why: Airflow 3 dropped the legacy SLA feature. dbt source freshness (warn after 2 hours, error after 6 hours on `_ingested_at`) and a freshness check on the latest `period_utc` in `fct_grid_hourly` fail loudly, and a failure callback on every task posts to a Slack incoming webhook once its retries are spent (logged only when no webhook is configured).

**Decision: DAGs baked into the Airflow image in production, mounted from disk locally.** Why: an image tag pins exactly which DAG code ran, which makes deployments auditable and rollbacks one command. Local development mounts the folder for fast iteration.

**Retries and timeouts.** Extraction tasks retry 3 times with exponential backoff and time out after 20 minutes; dbt model tasks retry twice. Every task has an `execution_timeout`, so a hung API call never blocks the schedule.

## DevOps

Everything lives in one Git repository, every component ships as its own container image, all AWS resources come from Terraform, and GitHub Actions gates every merge on tests and deploys on merge to `main`.

**Repository layout.**

```
gridpulse/
  CLAUDE.md                 # spec for coding assistants: conventions, pinned versions, domain rules
  docs/adr/                 # architecture decision records
  ingestion/                # extractors, pydantic models, tests, Dockerfile
  transform/                # dbt project: models, seeds, snapshots, macros, tests, Dockerfile
  semantic/                 # semantic API (FastAPI + MetricFlow), Dockerfile; cube/ for the optional comparison
  agent/                    # LangGraph graph, FastAPI app, Streamlit UI, evals, Dockerfile
  orchestration/            # Airflow DAGs, plugins, Dockerfile
  infra/
    terraform/modules/      # network, lake, catalog, eks, iam, ecr, rds, github_oidc
    terraform/envs/dev/     # dev state and variables
    terraform/envs/prod/
    helm/                   # values for Airflow; charts for the semantic API and agent
  local/                    # docker-compose and k3d config for local development
  .github/workflows/        # ci.yml, cd.yml, pr-cleanup.yml, nightly.yml
  Makefile                  # one command per task: make test, make up, make plan
```

**Decision: a monorepo.** Why: one pull request can change a dbt model, its MetricFlow metric, and the agent's eval case together, and CI tests them together. For a single team, the coordination cost of many repos buys nothing.

**Decision: trunk-based Git workflow.** Why: short-lived feature branches merge to `main` through pull requests with branch protection (required checks, one review, linear history). Conventional commit messages feed an automatic changelog. This is how most modern data teams work, and it keeps the history readable for reviewers.

**Decision: one image per component, built multi-stage, running as non-root.** Why: the extractor, dbt, semantic API, agent, and Airflow images change at different rates and have different dependencies. Multi-stage builds keep images small, non-root users and pinned slim base images satisfy basic security scans, and `hadolint` lints every Dockerfile.

**Decision: images tagged with the Git commit SHA.** Why: every running pod maps to an exact commit, so "what code produced this number?" always has an answer, and rollback means redeploying the previous tag.

**Kubernetes layout.** Namespaces `airflow`, `semantic`, and `agent`. Airflow installs from the official Helm chart; the semantic API and the agent use small in-repo charts. Every Deployment sets CPU and memory requests and limits, readiness and liveness probes, and a service account mapped to its IAM role through EKS Pod Identity. The AWS Load Balancer Controller provides one ingress. External Secrets Operator pulls secrets from SSM Parameter Store.

**Decision: develop on `k3d`, demo on EKS.** Why: the same Helm charts run on both, so local work proves the deployment without cloud cost. EKS is created with `terraform apply` before a demo or interview and destroyed after, which keeps monthly cost low while still proving real cloud deployment.

**Terraform modules.**

| Module | Creates |
| --- | --- |
| `network` | VPC, two availability zones, private and public subnets, one NAT gateway, S3 gateway endpoint |
| `lake` | Raw, lake, and Athena results buckets with encryption, versioning, lifecycle rules, and TLS-only policies |
| `catalog` | Glue databases, Athena workgroups with per-query scan limits |
| `ecr` | One repository per image, with scan-on-push and lifecycle rules |
| `eks` | Cluster, managed node group on Spot instances, Pod Identity, Load Balancer Controller |
| `iam` | One role per workload, scoped to exactly the buckets and databases it needs |
| `rds` | Small Postgres instance for Airflow metadata and the LangGraph checkpointer |
| `github_oidc` | GitHub OIDC provider and deploy roles limited to this repository |

**Decision: S3 remote state with native S3 locking, one state per environment.** Why: Terraform 1.10 and later can lock state with a lock file in S3, so no DynamoDB table is needed. Separate dev and prod states mean a mistake in dev cannot touch prod.

**Decision: an S3 gateway endpoint and Spot nodes.** Why: lake traffic from the cluster bypasses the NAT gateway (gateway endpoints are free, NAT data processing is not), and Spot instances cut node cost substantially. Airflow tasks are retryable, so Spot interruptions are acceptable.

**CI/CD pipelines.**

| Workflow | Trigger | Steps |
| --- | --- | --- |
| `ci.yml` | Pull request | Lint (`ruff`, `sqlfluff`, `yamllint`, `hadolint`); `pytest` for ingestion, agent, and DAG integrity; dbt slim CI build into `ci_pr_<n>`; Terraform `fmt`, `validate`, `tflint`, `checkov`, and `plan` posted as a PR comment; Docker builds; agent evals when `agent/` or `semantic/` changed |
| `cd.yml` | Merge to `main` | Build and push images tagged by SHA; `terraform apply` behind a GitHub environment that requires approval; `helm upgrade`; upload the prod dbt manifest to S3; publish dbt docs to GitHub Pages |
| `pr-cleanup.yml` | Pull request closed | Drop the `ci_pr_<n>` Glue databases and their S3 data |
| `nightly.yml` | Daily | Dependency and image vulnerability scans |

**Decision: dbt slim CI with deferral.** Why: `dbt build --select state:modified+ --defer` builds only changed models and their children, reading unchanged parents from production. CI stays fast and cheap even as the project grows, and it uses the prod manifest that `cd.yml` uploads.

**Decision: GitHub OIDC instead of stored AWS keys.** Why: GitHub Actions exchanges a short-lived token for a role scoped to this repository and branch. There is nothing to rotate or leak.

**Decision: manual approval on production applies.** Why: Terraform changes to production are shown as a plan in the pull request and applied only after an approver confirms in the GitHub environment. This shows change control without extra tools.

## Testing and validation

Every layer has its own tests, the fast ones block pull requests, and the slow or data-dependent ones run on a schedule and alert instead of blocking.

| Layer | Test | Tool | When it runs | Blocks merge? |
| --- | --- | --- | --- | --- |
| Ingestion | Pagination, retries, rate limiting, and schema drift handling against recorded API responses | `pytest` + `respx` fixtures | Every PR | Yes |
| Ingestion | Row completeness: rows received equal the API's `total` | Assertion in extractor | Every run | Fails the task |
| Ingestion | Record validation (types, required fields, allowed series codes) | `pydantic` | Every run | Fails the batch |
| Weather | Scaling and sentinel parsing (`+0215,1` → 21.5 °C, `9999` → null) | `pytest` | Every PR | Yes |
| dbt logic | Latest-version selection, DST local-time conversion, population-weighted temperature | dbt unit tests | Every PR | Yes |
| dbt data | Unique and not-null keys, relationships to dimensions, accepted fuel codes | dbt generic tests | Every PR and every run | Yes (error severity) |
| dbt data | Ranges: demand ≥ 0, temperature between −60 and 60 °C | `dbt-expectations` | Every run | Warn |
| dbt data | Reconciliation: generation by fuel sums to net generation within 2% per BA-hour | Custom singular test | Every run | Warn, alert above 1% of rows failing |
| dbt data | Interchange symmetry: flow A→B ≈ −(B→A) | Custom singular test | Every run | Warn |
| dbt data | Freshness: latest ingest within 2 h (warn) and 6 h (error) | dbt source freshness | Every run | Alert |
| dbt schema | Mart column names and types unchanged; semantic models and metrics parse and validate | dbt model contracts, dbt parse, mf validate-configs | Every PR | Yes |
| dbt correctness | Incremental output equals a full rebuild | `dbt_full_refresh_check` DAG | Monthly | Alert |
| Observability | Row-count and value anomalies per BA over time | Elementary | Every run | Alert |
| Semantic layer | Every metric returns the same value as a hand-written SQL reference query on a fixed date | `pytest` through the semantic API | Every PR touching `semantic/` | Yes |
| Agent | Validation rules reject bad queries (unknown metric, summed peaks, huge ranges) | `pytest` | Every PR | Yes |
| Agent | Golden-set query accuracy ≥ 90% | Eval harness | PRs touching `agent/` or `semantic/` | Yes |
| Agent | End-to-end answers and ground-check failures | Eval harness, live | Nightly | Alert |
| Orchestration | DAGs import, have no cycles, set retries and timeouts, use the `eia_api` pool | `pytest` DAG integrity tests | Every PR | Yes |
| Infrastructure | Format, validation, lint, security policies | `terraform fmt`/`validate`, `tflint`, `checkov` | Every PR | Yes |
| Kubernetes | Chart lint and manifest schema validation | `helm lint`, `kubeconform` | Every PR | Yes |
| Deployment | Smoke test: health endpoints respond and one known question returns the reference value | `pytest` post-deploy | After every deploy | Triggers rollback |

**Decision: block merges on deterministic tests only.** Why: tests that depend on live data or a live LLM can fail for reasons unrelated to the code change. Those run on a schedule and alert, so pull requests stay reliable and fast.

**Decision: reconciliation tests between related sources.** Why: generation by fuel and total net generation come from different EIA routes but must agree. Cross-source checks catch problems that single-column tests never see, and they are exactly what senior reviewers look for.

**Decision: warn, do not fail, on source-side data anomalies.** Why: if an operator reports a spike, failing the pipeline blocks all other regions' data. The row is flagged, the metric excludes it, an alert fires, and the revision audit shows whether the operator later fixed it.

**Decision: test the semantic layer against SQL ground truth.** Why: a metric definition can be syntactically valid but compute the wrong thing. Comparing each metric to an independently written SQL query on a fixed historical day proves the definitions are correct.

**Decision: record real API responses as test fixtures.** Why: tests run offline, fast, and free, and they cover real quirks (string values, partial pages) instead of invented ones. Refresh the fixtures when the API changes.

## Phased build plan

The build runs in nine phases, each a vertical slice with a checkable "done when" so you (or a coding assistant) always know whether the phase is finished. Effort figures are rough estimates for part-time work.

**Decision (revised 2026-10-12): build an MVP slice end to end first, then the depth phases.** Why: a thin slice (region-data → dbt → five metrics → minimal agent → one-command AWS up/down) is demoable in weeks instead of months and surfaces cross-layer problems early. Nothing in the phases below is dropped; they are reordered into Phase A (MVP) and Phase B (depth), tracked in `docs/STATUS.md`. The lake runs fully offline locally (see *Local and cloud runtime*), so AWS is only needed for the `aws` target and demos.

0. **Foundations** (about 3 days)
   - Repo layout, `CLAUDE.md`, `Makefile`, `pre-commit`, `uv` workspace, ADR template, CI workflow with linting.
   - Done when: `make lint test` passes locally and in GitHub Actions on an empty project.
1. **Lake and first extractor** (about 1–2 weeks)
   - Terraform `lake`, `catalog`, and `github_oidc` modules applied to dev. Extractor for `region-data` with pagination, rate limiting, `pydantic` validation, and recorded fixtures.
   - Done when: one week of data lands in S3 and the raw Iceberg table, rerunning the same window adds no new distinct rows, and the completeness assertion passes.
2. **First dbt slice** (about 1–2 weeks)
   - Seeds, `stg_eia__region_data`, `int_grid__latest_values`, `dim_balancing_authority`, `fct_grid_hourly` with contracts, unit tests, and generic tests. Slim CI into `ci_pr_<n>`.
   - Done when: a PR that changes one model builds only that model and its children in CI, and the DST unit tests pass.
3. **Full data coverage** (about 2 weeks)
   - Fuel-type and interchange extractors, NOAA weather, quality flags, revision audit, snapshots, reconciliation tests.
   - Done when: all marts build, reconciliation tests pass on at least 98% of BA-hours, and `fct_data_revisions` shows real revisions from re-pulled windows.
4. **Orchestration on `k3d`** (about 1–2 weeks)
   - Airflow 3 via Helm, all DAGs, Cosmos, the `eia_api` pool, alerts, and a one-year historical backfill (ADR-0005).
   - Done when: the one-year backfill completes (about 1,700 API calls, roughly an hour at EIA's 3–4 s per page) and freshness stays under 2 hours for 7 straight days.
5. **dbt Semantic Layer** (about 1–2 weeks)
   - Day 1 spike: compile and run a sum, a ratio, and a cumulative metric with MetricFlow on Athena; if it fails, add Trino on `k3d` reading the same Iceberg tables. Then: time spine, semantic models, all metrics and saved queries in dbt YAML, the semantic API service, caching, and SQL ground-truth tests.
   - Done when: `mf validate-configs` passes in CI, every metric matches its reference SQL on a fixed date, and `mf query` and the API return the same numbers.
6. **Agent** (about 2 weeks)
   - LangGraph graph, validation rules, Bedrock models, FastAPI, Streamlit, golden eval set of about 50 questions.
   - Done when: query accuracy is at least 90%, the ground-check catches a deliberately injected wrong number in a test, and an ambiguous question triggers a clarifying question.
7. **Cloud deployment** (about 1–2 weeks)
   - Terraform `network`, `eks`, `iam`, `ecr`, `rds`; `cd.yml`; Helm releases on EKS; post-deploy smoke test with rollback.
   - Done when: a merge to `main` deploys automatically after approval, the smoke test passes, and `terraform destroy` followed by `apply` restores the full platform from scratch.
8. **Portfolio polish** (about 1 week)
   - README with architecture diagram and a two-minute demo video, published dbt docs, ADR index, cost report, and a short write-up of one real data issue the platform caught.
   - Done when: a reviewer can understand the project from the README in five minutes and run `make up` locally.
9. **Optional learning tracks** (about 1 week each)
   - Hosted dbt Semantic Layer demo on a dbt platform trial with a Trino-based engine, querying the same metric YAML through the GraphQL API or dbt MCP server. Cube comparison: four metrics rebuilt in Cube with parity tests and an ADR.
   - Done when: a recorded demo shows the hosted layer answering the same question as the self-hosted API, and Cube's parity tests match MetricFlow's numbers.

## Cost control, risks, and decision log

The lake runs all the time for a few dollars a month; the Kubernetes stack runs only when you need it, and AWS Budgets alerts stop surprises. The figures below are approximate us-east-1 list prices from memory, so check the AWS pricing pages before you build.

| Component | When it runs | Approximate cost |
| --- | --- | --- |
| S3, Glue Catalog, Athena | Always | A few dollars per month at this data size (Athena charges about $5 per TB scanned) |
| EKS control plane | Demo windows only | About $0.10 per hour |
| NAT gateway | Demo windows only | About $0.045 per hour plus data processed |
| Spot worker nodes (2 × medium/large) | Demo windows only | Roughly $0.03–0.06 per hour each |
| RDS Postgres (smallest Graviton instance) | Demo windows only (stop when idle) | About $0.02 per hour |
| Bedrock (Claude) | Per question and nightly evals | Cents per day with the small model routing most calls |

**Decision: AWS Budgets alerts at $25 and $50 per month, created by Terraform.** Why: cost control should be code too, and an alert by email is the cheapest insurance against a forgotten cluster.

**Decision (revised 2026-10-12): accept gaps while the cluster is down, and close them with one catch-up run.** Why: EIA keeps full history, so a gap is recoverable. Replaying every missed hourly run is wasteful: two weeks down means about 336 runs, each re-pulling 72 hours. Instead the hourly DAG uses `catchup=False`, and a `catchup_gap` task on startup pulls from the last loaded `period_utc` to now in one window; gaps over 30 days become chunked monthly backfills through the `eia_api` pool. Paying for 24/7 compute just to avoid a recoverable gap is not worth it for a portfolio.

**Risks and mitigations.**

| Risk | Impact | Mitigation |
| --- | --- | --- |
| EIA API changes or outages | Ingestion fails | Recorded fixtures catch breaking changes in CI; raw responses allow reprocessing; failures alert |
| API key suspended during backfill | Backfill stalls | Rate limiter, the 2-slot pool, backoff, and chunked monthly backfills |
| Library version conflicts (Airflow 3, Cosmos, dbt-athena, LangGraph) | Build breaks or assistant writes outdated code | Pin versions in lockfiles and `CLAUDE.md`; upgrade one component at a time behind CI |
| MetricFlow SQL not fully compatible with Athena | Some metrics fail to compile or run | One-day spike at the start of Phase 5; fall back to Trino on EKS over the same Iceberg tables; keep complex logic in dbt marts |
| Forgotten EKS cluster | Unexpected bill | Budgets alerts; `make down` destroys compute; a tagging policy marks demo resources |
| Scope creep | Project never finishes | Phase gates; anything new goes to a "later" list in the README |

**Decision log.** Each bold "Decision" in this blueprint becomes an architecture decision record in `docs/adr/`. Use this template:

```markdown
# ADR-0007: Resolve EIA revisions with Iceberg MERGE over a 30-day lookback

Status: Accepted
Date: 2026-10-12

## Context
EIA revises past hours without a "last updated" field.

## Decision
Re-pull a rolling window and merge on (ba_code, series, period_utc).

## Alternatives considered
- Load only new hours: misses revisions.
- Full reload daily: ~8 years of data, slow and wasteful.

## Consequences
- Recent hours may change; the agent warns about this.
- Window length is a tunable trade-off between cost and completeness.
```

**Sources.** [EIA API v2 technical documentation](https://www.eia.gov/opendata/documentation.php) (5,000-row limit, pagination, string values, throttling, sort defaults); [EIA copyright and reuse policy](https://www.eia.gov/about/copyrights_reuse.php); [EIA API terms of service](https://www.eia.gov/opendata/terms-of-service.php); [dbt Semantic Layer quickstart](https://docs.getdbt.com/guides/sl-qs.md) (plan requirements, supported platforms, v1.12 YAML spec); [MetricFlow repository](https://github.com/dbt-labs/metricflow) (Apache 2.0 license, library use with a dbt adapter). Tool behavior for Airflow 3, Cube, Cosmos, Terraform, and LangGraph is from general knowledge as of mid-2026; confirm against current docs when pinning versions.

## Changelog

- 2026-10-12 — Added *Local and cloud runtime*: fully offline local mode (Lakekeeper, Trino, and S3-compatible storage), foundation/compute Terraform split with `make aws-up`/`aws-down`, and laptop memory and cleanup rules.
- 2026-10-12 — Reordered the build into an MVP slice (Phase A) and depth phases (Phase B); progress tracked in `docs/STATUS.md`.
- 2026-10-12 — Replaced "replay every missed hour" with a single `catchup_gap` run after downtime.
- 2026-10-12 — Fixed stale Cube references: evals, the nightly eval DAG, monorepo and image decisions, and Helm charts now point to MetricFlow and the semantic API. Cube remains only as the optional comparison track.
- 2026-10-12 — Local S3 storage switched from MinIO to SeaweedFS (ADR-0001); MinIO's community images were discontinued.
- 2026-10-12 — Ingestion: sort adds `type` as a third key (period + respondent alone is not unique); windows are half-open with EIA's inclusive `end` handled in the client; one Iceberg commit per run; locally the extractor runs in a container on the compose network because Lakekeeper vends container-internal endpoints and signs S3 requests remotely.
- 2026-10-12 — dbt: watermark-driven incremental merges replace the fixed `lookback_filter()` window; staging no longer collapses versions by hash (A → B → A correctness); BA seed generated from EIA's EIA-930 reference tables with a geographic IANA `time_zone` alongside EIA's reporting label `eia_time_zone`; marts store UTC as zone-less `timestamp(6)`; run manifests kept per attempt.
- 2026-10-12 — AWS foundation applied with Terraform (state bucket bootstrapped by script). One environment (dev) per AWS account: Glue database names carry no env prefix, so a future prod would live in its own account (AWS's recommended account-per-environment pattern). Engine differences found and isolated in dbt macros: Athena's UTC-converting timestamp cast (local time) and its Hive-catalog `timestamp` type (views, contracts, unit tests).
- 2026-10-12 — Semantic layer: the spike passed on Athena, so MetricFlow serves metrics directly on both engines and the Trino-on-EKS fallback is dropped (ADR-0002). Added `fct_grid_coverage_hourly` (a dense BA × hour table) as the `data_completeness` denominator; the semantic API renders time windows itself as typed, half-open filters.
- 2026-10-12 — Agent: the model provider is a setting (Bedrock default; Anthropic API and local Ollama as alternatives), with Claude 4.x defaults until this new account is enabled for 5.x. The golden set scores planned metric requests (not Cube queries) with a pinned "today"; clarify and inspect nodes move to B4 as planned.
- 2026-10-12 — Orchestration (MVP): Airflow 3 runs locally as `airflow standalone` with LocalExecutor, launching the extractor and dbt images via DockerOperator; the gap catch-up lives in the extractor (`--start auto` from a watermark) rather than a separate task. Local Lakekeeper has remote signing disabled (ADR-0001 follow-up): writers use direct S3 credentials, as IAM roles do on AWS.
- 2026-10-12 — AWS demo (MVP): the compute stack is VPC + EKS (Graviton Spot) + Pod Identity roles only; RDS, Airflow-on-EKS and the load balancer controller move to B2. No public ingress: the demo is reached with `kubectl port-forward`, so nobody else can spend the Bedrock budget. No customer-managed KMS key or control-plane log group, so repeated up/down cycles leave nothing billable behind. ECR repositories live in the foundation; images are arm64, tagged by Git SHA and immutable.
- 2026-10-13 — Agent: temporary, local-only OpenAI API provider while Bedrock is blocked account-wide (ADR-0003, revert checklist inside). API-key providers refuse to start in Kubernetes. Added gitleaks secret scanning to pre-commit and CI.
- 2026-10-13 — B1: fuel-type and interchange routes, `fct_generation_by_fuel_hourly`, `fct_interchange_hourly` (non-U.S. neighbours kept and flagged), reconciliation tests with a per-BA pass rate and a documented-exceptions seed (PJM interchange).
- 2026-10-13 — Quality flags: per-series `quality_status` on `fct_grid_hourly` instead of one row-level status; spike = one-hour outlier against both adjacent hours (var `spike_threshold`, 0.5).
- 2026-10-13 — Revision audit covers all three EIA routes (item = series, fuel or neighbour BA), with revision_type changed/filled/removed and hours_after_period.
- 2026-10-13 — Weather source: NOAA GHCNh replaces ISD (ISD stopped updating in August 2025; ADR-0004). Seed `ba_weather_stations` covers the six sample BAs with Census Vintage 2025 metro populations; temperature joins `fct_grid_hourly` and fills in on a later run when NOAA publishes.
- 2026-10-13 — `dim_balancing_authority` is built from `snap_ba_reference` (SCD2). Run manifests are also appended to `raw.ingestion_runs` (best effort; `gridpulse-extract manifests` backfills from S3) so dbt can build `fct_ingestion_runs` without reading JSON from S3.
- 2026-10-13 — B2 slice 1: all seven DAGs share one task factory; `GRIDPULSE_TASK_RUNTIME` picks DockerOperator (compose) or KubernetesPodOperator (k3d, EKS), and Kubernetes task env comes from per-component ConfigMaps/Secrets rather than DAG code. Cosmos renders `dbt_build` from the manifest baked into the Airflow image (one `dbt build --select <node>` task per node, unit tests left to CI). Lake maintenance and the full-refresh comparison are dbt macros (`adapter.dispatch` for Trino vs Athena). Assets renamed `raw_eia`/`raw_noaa`. Elementary moved to B6.
- 2026-10-13 — B2 slice 2: Airflow on k3d uses the official chart 1.22.0 (Airflow 3.3.2 image) with KubernetesExecutor, Airflow 3's simple auth manager, and remote task logs in object storage (SeaweedFS locally, S3 on AWS). Metadata lives in the shared Postgres (compose locally, RDS on AWS). DAGs are baked into the image on k3d as on EKS; the compose Airflow keeps mounting them for quick iteration.
- 2026-10-13 — B2 slice 3: alerts are a Slack incoming webhook only (no email); the mart freshness check is a dbt singular test on the latest demand hour in `fct_grid_hourly` (6 h), `warn` in dev builds and `error` in the scheduled `dbt_build`.
- 2026-10-13 — History window cut to one year (from 2025-10-01), loaded once with `make backfill-aws` from the laptop (ADR-0005); July 2018 becomes an optional extension.
- 2026-10-13 — One-year backfill done (63 BAs, 2025-10-01..2026-10-12). Staging now drops EIA's regional and US48 aggregate respondents (seed `eia_aggregate_respondents`). Reconciliation tests warn by default at full scale (ADR-0006).
