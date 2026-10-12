#!/usr/bin/env bash
# Tear down the AWS demo compute and prove nothing billable is left. The foundation (buckets,
# Glue, Athena, ECR, budgets) is not touched.
source "$(dirname "$0")/aws-common.sh"
started=$(date +%s)

step "Helm release and namespace"
if kubectl config get-contexts "$KUBE_CONTEXT" >/dev/null 2>&1; then
  helm uninstall gridpulse --kube-context "$KUBE_CONTEXT" -n "$NAMESPACE" --wait 2>/dev/null || true
  kubectl --context "$KUBE_CONTEXT" delete namespace "$NAMESPACE" --wait=true --timeout=3m 2>/dev/null || true
fi

step "Terraform: destroy compute"
tf_init
"${TF[@]}" destroy -input=false -auto-approve

step "Leftover check: resources tagged gridpulse:lifecycle=ephemeral"
leftovers=""
for _ in $(seq 1 12); do  # the tagging API lags deletes by a minute or two
  leftovers=$(aws resourcegroupstaggingapi get-resources \
    --tag-filters Key=gridpulse:lifecycle,Values=ephemeral \
    --query 'ResourceTagMappingList[].ResourceARN' --output text)
  [ -z "$leftovers" ] && break
  sleep 15
done
kubectl config delete-context "$KUBE_CONTEXT" >/dev/null 2>&1 || true
if [ -n "$leftovers" ]; then
  echo "STILL PRESENT (check and delete):"; echo "$leftovers" | tr '\t' '\n'
  exit 1
fi
echo "Nothing left. Down in $(( ($(date +%s) - started) / 60 )) min. Idle cost is the foundation only."
