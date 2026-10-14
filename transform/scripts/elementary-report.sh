#!/usr/bin/env bash
# Build Elementary's HTML report (test results, run history, freshness) from the `elementary`
# schema and upload it to <bucket>/reports/elementary/index.html. Runs in the transform image
# after each scheduled dbt build (dbt_build DAG). Configured only by environment variables, so
# the same task works on Docker (SeaweedFS, static keys) and on Kubernetes (pod IAM role):
#   GRIDPULSE_REPORTS_BUCKET   bucket to upload to (required)
#   DBT_TARGET                 local (Trino) or aws (Athena); default local
#   GRIDPULSE_S3_ENDPOINT, GRIDPULSE_S3_ACCESS_KEY, GRIDPULSE_S3_SECRET_KEY   local S3 only
set -euo pipefail

args=(
  send-report
  --project-dir "${DBT_PROJECT_DIR:-/app/transform}"
  --profiles-dir "${DBT_PROFILES_DIR:-/app/transform}"
  --config-dir "${DBT_PROJECT_DIR:-/app/transform}/edr"
  --target-path /tmp/edr
  --profile-target "${DBT_TARGET:-local}"
  --env "${GRIDPULSE_ENV:-dev}"
  --project-name gridpulse
  --disable-samples true
  --s3-bucket-name "${GRIDPULSE_REPORTS_BUCKET:?set GRIDPULSE_REPORTS_BUCKET}"
  --bucket-file-path reports/elementary/index.html
)
if [ -n "${GRIDPULSE_S3_ENDPOINT:-}" ]; then
  args+=(--s3-endpoint-url "$GRIDPULSE_S3_ENDPOINT"
    --aws-access-key-id "${GRIDPULSE_S3_ACCESS_KEY:?}"
    --aws-secret-access-key "${GRIDPULSE_S3_SECRET_KEY:?}"
    --aws-region-name "${GRIDPULSE_S3_REGION:-us-east-1}")
fi
exec edr "${args[@]}"
