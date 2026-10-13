#!/usr/bin/env bash
# Drop a pull request's slim-CI build on Athena: every Glue database named <prefix>_* (through
# the dbt macro that refuses short prefixes) and the S3 data under dbt/<prefix>_*.
#   infra/scripts/ci-cleanup.sh ci_pr_42
set -euo pipefail

prefix=${1:?usage: ci-cleanup.sh ci_pr_<number>}
[[ $prefix =~ ^ci_pr_[0-9]+$ ]] || { echo "refusing prefix '$prefix' (expected ci_pr_<number>)"; exit 2; }
bucket="gridpulse-${GRIDPULSE_ENV:-dev}-lake"

DBT_PROJECT_DIR=transform DBT_PROFILES_DIR=transform DBT_TARGET=aws \
  uv run --quiet dbt run-operation drop_prefixed_schemas --args "{prefix: $prefix}"

# Dropping a database removes its tables from Glue; the files are deleted here. Listing only the
# top-level prefixes under dbt/ keeps this fast however big the lake is.
for dir in $(aws s3api list-objects-v2 --bucket "$bucket" --prefix dbt/ --delimiter / \
  --query "CommonPrefixes[?starts_with(Prefix, 'dbt/${prefix}_')].Prefix" --output text); do
  [ "$dir" = None ] && continue
  echo "deleting s3://$bucket/$dir"
  aws s3 rm --recursive --only-show-errors "s3://$bucket/$dir"
done
