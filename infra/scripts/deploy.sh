#!/usr/bin/env bash
# Deploy one image tag to the running demo cluster and prove it works, or put the previous
# release back. Used by `make aws-up` and by CD (cd.yml, after approval).
#   infra/scripts/deploy.sh <image tag>
# helm --atomic undoes an upgrade whose pods never become ready; a failed smoke test (wrong
# numbers, not just dead pods) rolls back to the previous revision explicitly.
source "$(dirname "$0")/aws-common.sh"
TAG=${1:?usage: deploy.sh <image tag>}
CLUSTER="gridpulse-$ENV_NAME"

aws eks update-kubeconfig --name "$CLUSTER" --alias "$KUBE_CONTEXT" >/dev/null
previous=$(helm history gridpulse --kube-context "$KUBE_CONTEXT" -n "$NAMESPACE" --max 1 \
  -o json 2>/dev/null | python3 -c 'import json,sys; h=json.load(sys.stdin); print(h[-1]["revision"] if h else "")' \
  || true)

step "Helm: gridpulse release (tag $TAG; previous revision: ${previous:-none})"
helm upgrade --install gridpulse "$ROOT/infra/helm/gridpulse" \
  --kube-context "$KUBE_CONTEXT" --namespace "$NAMESPACE" --create-namespace \
  --set image.registry="$REGISTRY" --set image.tag="$TAG" --set env="$ENV_NAME" \
  --atomic --wait --timeout 10m
kubectl --context "$KUBE_CONTEXT" -n "$NAMESPACE" get pods

step "Smoke test"
if ! "$ROOT/infra/scripts/smoke.sh"; then
  if [ -n "$previous" ]; then
    step "Smoke test failed: rolling back to revision $previous"
    helm rollback gridpulse "$previous" --kube-context "$KUBE_CONTEXT" -n "$NAMESPACE" --wait --timeout 10m
  else
    step "Smoke test failed on the first install: nothing to roll back to"
  fi
  exit 1
fi
