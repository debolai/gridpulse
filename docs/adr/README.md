# Architecture decision records

Each record explains one decision that changed or sharpened the blueprint
([`docs/blueprint.md`](../blueprint.md)): the context, what was decided, the options set aside and
the consequences. New records copy [`0000-template.md`](0000-template.md).

| ADR | Decision | Status | Date |
| --- | --- | --- | --- |
| [0001](0001-seaweedfs-for-local-object-storage.md) | Use SeaweedFS, not MinIO, as local S3 storage | Accepted | 2026-10-12 |
| [0002](0002-metricflow-serves-metrics-on-trino-and-athena.md) | Serve metrics with open-source MetricFlow on both Trino and Athena | Accepted | 2026-10-12 |
| [0003](0003-temporary-openai-provider-for-local-development.md) | Temporary OpenAI API provider for local development while Bedrock is blocked | Accepted (temporary) | 2026-10-13 |
| [0004](0004-noaa-ghcnh-replaces-isd-for-weather.md) | NOAA GHCNh replaces ISD (Global Hourly) as the weather source | Accepted | 2026-10-13 |
| [0005](0005-one-year-of-history.md) | Load one year of history, not everything since July 2018 | Accepted | 2026-10-13 |
| [0006](0006-reconciliation-warns-at-full-scale.md) | Reconciliation checks warn instead of failing the build | Accepted | 2026-10-13 |
| [0007](0007-drop-seven-day-freshness-criterion.md) | Drop the 7-day freshness soak from B2's done-when | Accepted | 2026-10-13 |
| [0008](0008-coincident-peak-over-fixed-scopes.md) | Coincident peak is served for fixed scopes, not arbitrary sets of BAs | Accepted | 2026-10-13 |
| [0009](0009-cd-deploys-only-when-the-demo-cluster-is-up.md) | CD deploys to EKS only when the demo cluster is up | Accepted | 2026-10-13 |
| [0010](0010-demo-agent-memory-in-cluster-postgres.md) | The demo keeps agent conversations in a Postgres pod, not RDS | Accepted | 2026-10-13 |
