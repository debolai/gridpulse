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
make test-integration  # prove Trino can write and read Iceberg tables
make down              # stop (keeps data); `make reset` wipes it
```

## Data credits
Grid data: U.S. Energy Information Administration (EIA), used under EIA's copyright and reuse policy and API terms of service. Weather: NOAA Global Hourly (ISD), public domain.
