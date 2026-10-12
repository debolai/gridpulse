# GridPulse

Grid operations analytics platform: hourly U.S. electricity grid data (EIA-930) and NOAA weather, turned into governed metrics that analysts and an LLM assistant can query without writing SQL.

Runs fully offline on a laptop (SeaweedFS S3 + Lakekeeper Iceberg catalog + Trino) and on AWS (S3 + Glue + Athena + EKS), with one-command spin-up and tear-down for demos.

- Design and decisions: [`docs/blueprint.md`](docs/blueprint.md)
- Progress: [`docs/STATUS.md`](docs/STATUS.md)
- Architecture decision records: [`docs/adr/`](docs/adr/)

## Quick start

```bash
make setup   # install pinned tools and git hooks
make lint test
make help    # all commands

make up-lake           # local lake: Trino at http://localhost:8080, catalog UI at http://localhost:8181/ui
make test-integration  # prove Trino can write and read Iceberg tables, and reruns are idempotent
make extract-sample START=2026-10-01 END=2026-10-08   # load a week of EIA data for 6 sample BAs (needs EIA_API_KEY in .env)
make dbt-build         # build and test the dbt models (staging → intermediate → marts) on the local lake
make dbt-docs          # browse model docs and lineage at http://localhost:8081
make semantic-api      # governed metrics over HTTP: http://localhost:8090/docs
make mf ARGS="query --metrics demand --group-by balancing_authority"   # MetricFlow CLI
make agent-api         # the assistant (LangGraph + Claude): http://localhost:8091/docs
make agent-ui          # Streamlit demo UI
make agent-eval        # golden-set accuracy (target ≥ 90%)
make down              # stop (keeps data); `make reset` wipes it
```

## Data credits
Grid data: U.S. Energy Information Administration (EIA), used under EIA's copyright and reuse policy and API terms of service. Weather: NOAA Global Hourly (ISD), public domain.
