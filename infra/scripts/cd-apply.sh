#!/usr/bin/env bash
# CD: plan and apply the dev foundation stack. Runs only in the `production` environment, i.e.
# after the owner approved the run in GitHub (the PR already showed the same plan).
# The budget alert email comes from state (it is git-ignored locally) and is masked in logs.
set -euo pipefail

dir=infra/terraform/envs/dev/foundation
account=$(aws sts get-caller-identity --query Account --output text)
terraform -chdir="$dir" init -input=false -backend-config="bucket=gridpulse-tfstate-$account" >/dev/null
email=$(terraform -chdir="$dir" state pull | jq -r '
  .resources[] | select(.type == "aws_budgets_budget")
  | .instances[0].attributes.notification[0].subscriber_email_addresses[0]')
if [ -n "${GITHUB_ACTIONS:-}" ]; then echo "::add-mask::$email"; fi

terraform -chdir="$dir" plan -input=false -no-color -out=cd.tfplan -var "budget_alert_email=$email" \
  | tee /tmp/cd-plan.txt | grep -E '^Plan:|^No changes|will be (created|updated|destroyed)'
if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
  {
    echo "### Terraform apply (foundation)"
    echo
    grep -E '^Plan:|^No changes' /tmp/cd-plan.txt || true
  } >> "$GITHUB_STEP_SUMMARY"
fi
terraform -chdir="$dir" apply -input=false -no-color cd.tfplan | tail -1
rm -f "$dir/cd.tfplan" /tmp/cd-plan.txt
