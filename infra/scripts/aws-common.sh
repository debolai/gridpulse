# Shared settings for the aws-* scripts. Sourced, not executed.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export AWS_PROFILE="${AWS_PROFILE:-gridpulse}"
export AWS_REGION="${AWS_REGION:-us-east-1}"
ENV_NAME="${GRIDPULSE_ENV:-dev}"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
REGISTRY="${ACCOUNT}.dkr.ecr.${AWS_REGION}.amazonaws.com"
COMPUTE_DIR="$ROOT/infra/terraform/envs/$ENV_NAME/compute"
TF=(terraform -chdir="$COMPUTE_DIR")
KUBE_CONTEXT="gridpulse-$ENV_NAME"
NAMESPACE=gridpulse

tf_init() {
  "${TF[@]}" init -input=false -backend-config="bucket=gridpulse-tfstate-${ACCOUNT}" >/dev/null
}

step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
