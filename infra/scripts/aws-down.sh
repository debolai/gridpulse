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
# The tagging API keeps listing deleted resources for up to an hour (NAT gateways, VPC endpoints,
# security groups), so each listed EC2 resource is confirmed against EC2 itself.
still_exists() {
  local arn=$1 id=${1##*/}
  case "$arn" in
    *:natgateway/*)
      [ "$(aws ec2 describe-nat-gateways --nat-gateway-ids "$id" \
        --query 'NatGateways[0].State' --output text 2>/dev/null || echo deleted)" != deleted ] ;;
    *:vpc-endpoint/*)
      [ "$(aws ec2 describe-vpc-endpoints --vpc-endpoint-ids "$id" \
        --query 'VpcEndpoints[0].State' --output text 2>/dev/null || echo deleted)" != deleted ] ;;
    *:security-group/*) aws ec2 describe-security-groups --group-ids "$id" >/dev/null 2>&1 ;;
    *:subnet/*) aws ec2 describe-subnets --subnet-ids "$id" >/dev/null 2>&1 ;;
    *:vpc/*) aws ec2 describe-vpcs --vpc-ids "$id" >/dev/null 2>&1 ;;
    *) true ;;  # anything else counts as present until it leaves the tag index
  esac
}
leftovers=""
for _ in $(seq 1 12); do
  leftovers=""
  for arn in $(aws resourcegroupstaggingapi get-resources \
    --tag-filters Key=gridpulse:lifecycle,Values=ephemeral \
    --query 'ResourceTagMappingList[].ResourceARN' --output text); do
    if still_exists "$arn"; then leftovers="$leftovers $arn"; fi
  done
  [ -z "$leftovers" ] && break
  sleep 15
done
kubectl config delete-context "$KUBE_CONTEXT" >/dev/null 2>&1 || true
if [ -n "$leftovers" ]; then
  echo "STILL PRESENT (check and delete):"; echo "$leftovers" | tr ' ' '\n' | sed '/^$/d'
  exit 1
fi
echo "Nothing left. Down in $(( ($(date +%s) - started) / 60 )) min. Idle cost is the foundation only."
