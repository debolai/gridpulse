#!/usr/bin/env bash
# Run the extractor container against the AWS dev lake (S3 + Glue) from this laptop.
#   infra/scripts/extract-aws.sh eia --route region-data --start 2026-07-01 --end 2026-10-12 --respondents PJM
# Short-lived SSO credentials are passed through a temp env file (mode 600, deleted on exit),
# never on the command line. In the cloud the same image gets credentials from its pod role.
set -euo pipefail
PROFILE="${AWS_PROFILE:-gridpulse}"
ENV_NAME="${GRIDPULSE_ENV:-dev}"
REGION="${AWS_REGION:-us-east-1}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

docker compose -f "$ROOT/local/compose.yaml" build -q extractor

umask 077
creds="$(mktemp)"
trap 'rm -f "$creds"' EXIT
aws configure export-credentials --profile "$PROFILE" --format env-no-export > "$creds"
cat >> "$creds" <<VARS
AWS_REGION=$REGION
GRIDPULSE_CATALOG_TYPE=glue
GRIDPULSE_RAW_BUCKET=gridpulse-$ENV_NAME-raw
GRIDPULSE_S3_REGION=$REGION
VARS

docker run --rm --env-file "$ROOT/.env" --env-file "$creds" gridpulse/ingestion:local "$@"
