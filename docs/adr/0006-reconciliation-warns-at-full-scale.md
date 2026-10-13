# ADR-0006: Reconciliation checks warn instead of failing the build

Status: Accepted
Date: 2026-10-13

## Context
B1 made the two reconciliation tests (fuel mix vs net generation, neighbour flows vs total
interchange) fail the build when a BA reconciled on fewer than 98% of its hours, because all
six sample BAs passed over July-October 2026 (PJM interchange aside, listed as an exception).
The one-year backfill for every BA (ADR-0005) changed the picture: on Athena over
2025-10-01..2026-10-12, 9 of 63 BAs miss the fuel-mix pass rate and 21 miss the interchange
pass rate. Even ERCO, at 100% in the sample, reconciles fuel on 97.6% of hours. The gaps are
source-side and come in two shapes: steady offsets (SWPP's fuels run a median 19.6 MWh off
net generation, PJM's 357 MWh) and episodes of partial reports in BAs that otherwise match
exactly (AZPS, PACW, NWMT, WALC: median gap 0). The blueprint already says to warn, not fail,
on source-side anomalies, so one BA's bad report never blocks every other BA's data.

## Decision
Both tests take their severity from the dbt var `reconciliation_severity`, default `warn`.
They still run on every build and list each failing BA with its pass rate. The tolerance (1%
or 1 MWh) and pass rate (98%) are unchanged, and `reconciliation_exceptions` stays for known,
explained cases. A strict run sets `--vars '{reconciliation_severity: error}'`.

## Alternatives considered
- List all 9 + 21 BAs in `reconciliation_exceptions`: an exception list that large stops
  meaning anything, and it would need re-measuring every month.
- Loosen the tolerance or pass rate until everything passes: hides real problems for the BAs
  that do reconcile.
- Keep `error`: the scheduled dbt_build would fail every run on source data we can't fix.

## Consequences
- Builds stay green; reconciliation problems surface as warnings, not alerts, until a per-BA
  reconciliation column (STATUS "Deferred") and Elementary (B6) report them over time.
- A pipeline bug that broke reconciliation for every BA would also only warn; the
  full-refresh check, contracts and relationships tests remain the hard gates.
- The semantic layer (B3) should exclude or caveat hours that fail reconciliation for metrics
  that combine routes (e.g. renewable share vs net generation).
