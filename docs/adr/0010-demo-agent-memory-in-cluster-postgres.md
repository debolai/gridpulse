# ADR-0010: The demo keeps agent conversations in a Postgres pod, not RDS

Status: Accepted
Date: 2026-10-13

## Context
The blueprint puts the LangGraph checkpointer "on the same database instance as Airflow's
metadata, in a separate database", on RDS. In practice the EKS demo runs only the semantic API
and the assistant; Airflow runs on k3d, and the compute stack has no RDS. The demo is created
for a few hours and destroyed (ADR-0009), so its conversations don't outlive it anyway.

## Decision
The Helm chart runs a small Postgres (same pinned image as compose) as the `agent-memory`
Deployment, with an `emptyDir` volume. Its password is generated on first install, kept across
upgrades, and reaches the agent only through the `agent-memory` Secret
(`GRIDPULSE_AGENT_CHECKPOINT_DSN`). Locally the agent uses the `agent` database on the compose
Postgres.

## Alternatives considered
- RDS now: matches the blueprint, but adds an instance, a subnet group, a security group and a
  secret path for one small database that is thrown away with the demo; about 5-10 more
  minutes per `make aws-up` and some monthly cost if left running.
- In memory (no Postgres): conversations would be lost on every pod restart, and the deployed
  agent would differ from local.

## Consequences
- Follow-ups and clarifications work in the demo as they do locally.
- A restart of the `agent-memory` pod loses conversations; acceptable for a demo.
- When Airflow moves to EKS with RDS, the agent switches to an `agent` database there by changing
  the DSN in the Secret; the agent code doesn't change.
