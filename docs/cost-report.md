# Cost report (dev environment)

How much GridPulse costs to run on AWS, and why it stays small. Measured on 2026-10-14, at the end
of phase B5. Prices are AWS us-east-1 list prices; check them against the
[AWS pricing pages](https://aws.amazon.com/pricing/) before relying on them.

## Summary

| Mode | What is running | Cost |
| --- | --- | --- |
| Idle (always) | Foundation: S3 buckets, Glue catalog, Athena workgroups, ECR, budgets, GitHub OIDC roles | about $0.10-1 per month, mostly ECR image storage |
| Demo | Compute: VPC with one NAT gateway, EKS control plane, 2 Spot Graviton nodes, the APIs | about $0.20-0.25 per hour while up |
| Local | Everything on the laptop (SeaweedFS, Lakekeeper, Trino, Airflow on k3d) | $0 |

Month to date (2026-10-01 to 2026-10-14), the account's budget reports **$0.52** actual spend,
including several demo sessions and the one-year backfill. Two budgets alert by email:
`gridpulse-monthly` ($50 a month, from the Terraform `budgets` module) and a $20 one created in
the AWS console.

## Idle: the foundation stack

| Item | Measured | List price | Per month |
| --- | --- | --- | --- |
| S3 raw bucket (Iceberg raw tables, API pages) | 0.48 GB | $0.023/GB-month | $0.01 |
| S3 lake bucket (dbt-built tables) | 0.35 GB | $0.023/GB-month | $0.01 |
| S3 Athena results (lifecycle-expired) | under 0.01 GB | $0.023/GB-month | $0.00 |
| ECR (4 repositories, up to 10 tags each by lifecycle rule) | about 7 GB listed (shared layers are billed once) | $0.10/GB-month | under $0.70 |
| Glue Data Catalog | well under 1 million objects | free tier | $0.00 |
| Athena | per query: $5 per TB scanned, 10 MB minimum | | cents; $0.07 on the backfill day |
| Budgets, IAM, OIDC provider | | free | $0.00 |

The data is small: a year of hourly data for every U.S. balancing authority (9.7 million raw rows
across three routes, plus weather) fits in under 1 GB of compressed Parquet.

## Demo: the compute stack (per hour while up)

| Item | List price | Per hour |
| --- | --- | --- |
| EKS control plane | $0.10/hour | $0.100 |
| NAT gateway (one, shared by both AZs) | $0.045/hour + $0.045/GB processed | $0.045 + data |
| NAT gateway public IPv4 | $0.005/hour | $0.005 |
| 2 x t4g.large Spot (Graviton; on-demand $0.0672/hour) | Spot $0.023-0.032/hour (us-east-1, 13 Oct 2026) | about $0.05-0.06 |
| 2 x 20 GB gp3 node volumes | $0.08/GB-month | about $0.004 |
| **Total** | | **about $0.21-0.22, plus NAT data** |

A demo session (16 min `make aws-up`, use, 13 min `make aws-down`) costs about $0.30-0.50. The
B5 CD test kept the demo up about an hour.

## Why it stays cheap

- **Ephemeral compute.** EKS, nodes and the NAT gateway exist only during a demo. `make aws-down`
  destroys them and then checks that nothing billable is left (ADR-0009).
- **S3 gateway endpoint.** Lake traffic from the cluster bypasses the NAT gateway, so it isn't
  charged per GB.
- **Spot and Graviton nodes.** Cheaper per hour; the workloads are stateless or retryable.
- **Athena scan limits.** Each workgroup caps bytes scanned per query, so a bad or LLM-generated
  query can't run up a bill. Partitioned Iceberg tables keep scans small.
- **One year of history, not seven** (ADR-0005).
- **Local first.** Development, CI and the integration tests run on the local engine or on
  GitHub's free runners for public repositories, not on AWS.
- **Lifecycle rules.** Athena results expire; ECR keeps 10 tags per repository and deletes
  untagged images after a day.
- **Budgets with email alerts** at 50% and 100%.

## Caveat

AWS Cost Explorer processes cost data 24-48 hours late, so on 2026-10-14 it showed only $0.15
(Athena, S3, KMS on 2026-10-13) and not yet the demo hours. The demo figures above are therefore
list-price estimates; they will be checked against Cost Explorer once the data is in.
