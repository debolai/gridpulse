# ADR-0002: Serve metrics with open-source MetricFlow on both Trino and Athena

Status: Accepted
Date: 2026-10-12

## Context
The blueprint planned a one-day spike before building the semantic layer. MetricFlow writes
SQL for a specific engine, and Athena support was unconfirmed. The fallback was to run Trino
on EKS over the same Iceberg tables. Since then, dbt-core 1.12 has started depending on
MetricFlow, and `dbt-metricflow` 0.15 ships official `dbt-trino` and `dbt-athena` extras.

## Decision
Use `dbt-metricflow[dbt-trino,dbt-athena]` (MetricFlow 0.213), wrapped by our FastAPI semantic API, on
both engines: Trino locally and Athena on AWS. No Trino-on-EKS fallback is needed.

Evidence, 2026-10-12, sample data (6 BAs, Jul–Oct 2026):
- `mf validate-configs` reports 0 errors and 0 warnings on both engines, including the checks run
  against the live warehouse.
- A sum (`demand`, `peak_demand`), ratios (`data_completeness`, plus averages for forecast
  error and bias), a cumulative metric (`demand_month_to_date`) and a dimension join (by
  interconnection and local hour) return identical results on Trino and Athena.
- Every metric equals hand-written SQL on a fixed window (integration tests, relative tolerance
  1e-9).

## Gotchas found, and how they are handled
1. **Time bounds snap to the query grain.** With an hourly time dimension and a day-grain
   query, `--end-time 2026-09-02T23:00` became `<= '2026-09-02'`, which keeps only the first
   hour of the last day. The API never uses MetricFlow's start/end parameters. It renders a
   half-open `[start, end)` filter on `metric_time` at hour grain, with typed `TIMESTAMP`
   literals. Trino and Athena also reject comparing a timestamp to a string.
2. **Cumulative metrics re-aggregate with `first` by default.** A daily month-to-date showed the
   day's first hour. Set `period_agg: last`.
3. **Partial parsing keeps stale metric definitions.** A changed `period_agg` didn't reach
   `semantic_manifest.json` until `dbt parse --no-partial-parse`. `make semantic-manifest` always
   does a full parse.
4. **Dimensions are scoped to the primary entity.** Columns on `fct_grid_hourly` are addressed
   as `grid_hour__<name>`. The API publishes the exact names in `GET /metrics` and rejects
   unknown ones with a clear message.

## Alternatives considered
- Trino on EKS as the serving engine: it works, but adds an always-on cluster cost, and Athena already works.
- Hosted dbt Semantic Layer: needs a paid plan and does not list Athena. It remains the optional B7 demo.
- Cube: kept as the B7 comparison track, outside the production path.

## Consequences
- One set of metric definitions serves both runtimes with no engine-specific metric YAML.
- The API, not the caller, owns time-window semantics. Agent requests stay simple and safe.
- MetricFlow upgrades are pinned and must be re-tested against the ground-truth suite.
