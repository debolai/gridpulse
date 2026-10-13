# ADR-0007: Drop the 7-day freshness soak from B2's done-when

Status: Accepted
Date: 2026-10-13

## Context
The blueprint's B2 done-when required "freshness stays under 2 hours for 7 straight days": a
soak test proving the hourly schedule, retries and alerts hold up unattended. In B2, Airflow
runs on k3d on the owner's laptop and writes to the AWS lake with an SSO session. Passing the
soak would need the laptop awake for 168 hours and a session that does not expire (SSO
sessions last hours), and it would keep AWS spend running between demos, against the
"AWS compute is ephemeral" rule. A missed hour restarts the week.

## Decision
B2 is done when all DAGs run green on k3d and the one-year backfill completes. Freshness is
enforced continuously instead of proven once: dbt source freshness (warn 2 h, error 6 h), the
`fct_grid_hourly` freshness test (error in the scheduled `dbt_build`), and a Slack alert on
every task failure.

## Alternatives considered
- Move the 7-day soak to B5, where Airflow runs on EKS with an IAM role: a fair test there,
  but the owner chose not to carry it as a gate.
- A 24-hour soak locally: still needs the laptop awake and long-lived credentials, and proves
  little more than the checks already do.

## Consequences
- No recorded multi-day uptime figure for the pipeline; the checks catch staleness when it
  happens but do not show a track record.
- Long-running problems (credential expiry, slow leaks, EIA rate-limit drift) surface first
  in production rather than in a soak.
