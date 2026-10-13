# ADR-0008: Coincident peak is served for fixed scopes, not arbitrary sets of BAs

Status: Accepted
Date: 2026-10-13

## Context
The blueprint defined `coincident_peak_demand` as "maximum over hours of demand summed across
selected BAs". That needs two aggregations in a row: a sum over BAs per hour, then a max over
hours. MetricFlow 0.213 has no metric type for it: simple metrics aggregate once, derived and
ratio metrics combine already-aggregated values, and cumulative metrics only offer first, last
or average per period. Over the year on Athena, a few BAs report only part of the time (BHBA,
SWPW and WACM started mid-year; the Western interconnection has every BA reporting in 83% of
hours, Eastern 97%, ERCOT 100%).

## Decision
A mart, `fct_demand_scope_hourly`, sums demand per hour for fixed scopes: each
interconnection, each EIA region, and the Lower 48 (`scope_type`, `scope_code`). The metric is
a plain `max` over it and must be filtered or grouped to one scope (the agent's validator
enforces this). Every expected hour is kept, with `bas_expected`, `bas_reported` and
`bas_flagged`; the `is_complete` dimension restricts to hours where every BA reported. A
missing BA can only lower an hour's sum, so the default includes all hours.

## Alternatives considered
- Two-stage query in the semantic API (MetricFlow's SQL for demand by hour, wrapped in a
  max): supports any set of BAs, but the metric would live outside the dbt YAML, `mf query`
  could not reproduce it, and it would be a second query path to test and secure.
- Only hours where every BA reported: drops 17% of Western hours, which can include the true
  peak.
- EIA's own regional and US48 aggregates (kept in raw): cover the same scopes, but would not
  follow our revision handling and quality flags, and EIA has no interconnection totals.

## Consequences
- "Combined peak of PJM and MISO" is not answerable; the agent should say so or offer a scope.
- Validated against EIA's published aggregates over 2025-10-01..2026-10-12: US48, CAL and TEX
  peaks match exactly (753,630 / 61,700 / 91,075 MW); median hourly gap 0, p99 1.1% (US48).
- Adding a scope (e.g. ISO/RTO footprints) is a new `scope_type` in the mart, no metric change.
