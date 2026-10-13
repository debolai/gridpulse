#!/usr/bin/env bash
# Read-only `terraform plan` of the dev foundation and compute stacks, written as Markdown for
# a pull-request comment. No state lock is taken, so read-only credentials (the CI role) are
# enough. The budget alert email (git-ignored tfvars locally) is read from state, masked in
# logs and replaced in the plan text: the repository is public.
#   infra/scripts/ci-plan.sh [out.md]
set -euo pipefail

out=${1:-plan.md}
work=$(mktemp -d)
account=$(aws sts get-caller-identity --query Account --output text)
bucket="gridpulse-tfstate-$account"
status=0

{
  echo "<!-- gridpulse-terraform-plan -->"
  echo "### Terraform plan (dev)"
  echo
  echo "Read-only plan against the live state. \`compute\` is the ephemeral demo stack: while the demo is down it plans a full create, which is expected."
} > "$out"

for stack in foundation compute; do
  dir="infra/terraform/envs/dev/$stack"
  terraform -chdir="$dir" init -input=false -reconfigure -backend-config="bucket=$bucket" >/dev/null
  vars=()
  email=""
  if [ "$stack" = foundation ]; then
    email=$(terraform -chdir="$dir" state pull | jq -r '
      .resources[] | select(.type == "aws_budgets_budget")
      | .instances[0].attributes.notification[0].subscriber_email_addresses[0]')
    if [ -n "${GITHUB_ACTIONS:-}" ]; then echo "::add-mask::$email"; fi
    vars=(-var "budget_alert_email=$email")
  fi
  if terraform -chdir="$dir" plan -lock=false -input=false -no-color ${vars[@]+"${vars[@]}"} \
    > "$work/$stack.txt" 2>&1; then
    summary=$(grep -E '^Plan:|^No changes' "$work/$stack.txt" | head -1 || true)
  else
    summary="**plan failed**"
    status=1
  fi
  plan=$(tail -c 25000 "$work/$stack.txt")
  if [ -n "$email" ]; then plan=${plan//"$email"/<budget alert email>}; fi
  {
    echo
    echo "**$stack**: ${summary:-see output}"
    echo
    echo "<details><summary>Plan output</summary>"
    echo
    echo '```'
    echo "$plan"
    echo '```'
    echo "</details>"
  } >> "$out"
done

rm -rf "$work"
exit "$status"
