# ADR-0009: CD deploys to EKS only when the demo cluster is up

Status: Accepted
Date: 2026-10-13

## Context
The blueprint's `cd.yml` runs `helm upgrade` on every merge to `main`, and the cloud phase is
done when "a merge to main deploys automatically after approval". But the project's AWS compute
is ephemeral: EKS, its nodes and the NAT gateway exist only around a demo (`make aws-up`, then
`make aws-down`), and only the foundation stack (S3, Glue, Athena, ECR, budgets) stays up. Most
merges happen while there is no cluster to deploy to. Creating one per merge takes about
15-20 minutes and costs money each time.

## Decision
On every merge to `main`, CD always:
- pushes every image to ECR, tagged with the commit SHA;
- uploads the dbt manifest that slim CI defers to;
- applies the foundation stack's Terraform after an approval in the `production` environment.

If the demo cluster is running, CD also deploys the new tags with `helm upgrade`, runs the
smoke test, and runs `helm rollback` when it fails. If no cluster is running, the deploy job
is skipped with a notice in the run summary; the next `make aws-up` deploys the latest pushed
tags.

## Alternatives considered
- Bring the cluster up on every merge, deploy, test, tear it down: proves the full path on
  every merge, but costs about 20 minutes and some dollars per merge for no user.
- Manual deploy only (`workflow_dispatch`): simplest, but a merge would never reach a running
  demo on its own, and the approval-gated path would go untested.

## Consequences
- The cloud done-when is met by a merge made while the demo is up: approval, deploy, smoke
  test, and a rollback test.
- Images and the manifest are always current in AWS, so `make aws-up` deploys what is on
  `main`, by SHA.
- A merge while the demo is down deploys nothing; the run summary says so, so it isn't mistaken
  for a deploy.
