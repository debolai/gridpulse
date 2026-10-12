#!/usr/bin/env bash
# Bring up the AWS demo: compute (VPC, EKS) -> images to ECR -> Helm release -> smoke test.
# The plan for this stack was reviewed once (`make aws-plan`); each run recreates the same
# resources, so apply runs unattended. Cost while up: about $0.20-0.25/hour.
source "$(dirname "$0")/aws-common.sh"
started=$(date +%s)

step "Terraform: compute stack (about 12-15 minutes on a fresh create)"
tf_init
"${TF[@]}" apply -input=false -auto-approve
CLUSTER="$("${TF[@]}" output -raw cluster_name)"

step "kubectl context: $KUBE_CONTEXT"
aws eks update-kubeconfig --name "$CLUSTER" --alias "$KUBE_CONTEXT" >/dev/null
kubectl --context "$KUBE_CONTEXT" get nodes -o wide

step "Images: build arm64 and push to ECR (skipped if this tag is already there)"
TAG="$(git -C "$ROOT" rev-parse --short=12 HEAD)"
if [ -n "$(git -C "$ROOT" status --porcelain)" ]; then TAG="${TAG}-dirty-$(date +%s)"; fi
aws ecr get-login-password | docker login --username AWS --password-stdin "$REGISTRY" >/dev/null
for component in semantic agent; do
  repo="gridpulse/$component"
  if aws ecr describe-images --repository-name "$repo" --image-ids imageTag="$TAG" >/dev/null 2>&1; then
    echo "$repo:$TAG already in ECR"
  else
    docker build -q --platform linux/arm64 -f "$ROOT/$component/Dockerfile" -t "$REGISTRY/$repo:$TAG" "$ROOT" >/dev/null
    docker push -q "$REGISTRY/$repo:$TAG" >/dev/null
    echo "pushed $repo:$TAG"
  fi
done

step "Helm: gridpulse release (tag $TAG)"
helm upgrade --install gridpulse "$ROOT/infra/helm/gridpulse" \
  --kube-context "$KUBE_CONTEXT" --namespace "$NAMESPACE" --create-namespace \
  --set image.registry="$REGISTRY" --set image.tag="$TAG" --set env="$ENV_NAME" \
  --wait --timeout 10m
kubectl --context "$KUBE_CONTEXT" -n "$NAMESPACE" get pods

step "Smoke test"
"$ROOT/infra/scripts/smoke.sh"

step "Up in $(( ($(date +%s) - started) / 60 )) min. Open the demo:"
echo "  kubectl --context $KUBE_CONTEXT -n $NAMESPACE port-forward svc/agent-ui 8501:8501   # http://localhost:8501"
echo "  kubectl --context $KUBE_CONTEXT -n $NAMESPACE port-forward svc/semantic-api 8090:8090   # http://localhost:8090/docs"
echo "When done: make aws-down"
