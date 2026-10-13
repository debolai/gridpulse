# ADR-0005: Load one year of history, not everything since July 2018

Status: Accepted
Date: 2026-10-13

## Context
The blueprint started the history at July 2018, when EIA-930 generation by fuel type begins, so
every metric would cover the same span. Nothing in the app depends on that date: the semantic
layer, the agent and the dashboards already work end to end on about 100 days of sample data.
Loading eight years for every balancing authority means roughly 13,000 EIA requests (several
hours at EIA's 3-4 s per page), about 64 million raw rows, and it would first need partition-
scoped rebuilds for the weather and quality-flag models (today they rebuild in full). The owner
asked to keep development moving and to cut the window to one or two years.

## Decision
Load one year: 2025-10-01 to the present, every balancing authority, once, into the AWS dev
lake with `make backfill-aws` (monthly chunks, two lanes to match the `eia_api` pool). The
hourly and daily DAGs keep it current from there. Weather stays on the six sample BAs for now
(other BAs have no temperature until their stations are added to the seed). The backfill runs
from the laptop with the extractor image rather than from Airflow on EKS, which keeps B2 free
of an RDS + EKS deployment.

## Alternatives considered
- Everything since July 2018: the original plan; hours of loading and two model rewrites
  before the first answer, for history the demo questions rarely need.
- Two years: about twice the load (~1 h 50 min); adds a second year for seasonal comparisons.
  Easy to add later with the same command.
- Backfill through Airflow on EKS: proves the cloud deployment, but costs the RDS and EKS
  setup now; deferred.

## Consequences
- Year-over-year questions work only within the last year; the agent should say so when asked
  about earlier periods (B4).
- Extending the history is one command (`make backfill-aws START=2018-07-01 END=2025-10-01`),
  after the partition-scoped rebuilds listed under "Deferred" in STATUS.
- Metrics stay comparable across fuel mix, demand and interchange: all start on the same day.
