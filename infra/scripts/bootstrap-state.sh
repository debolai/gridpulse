#!/usr/bin/env bash
# One-time, idempotent: create the S3 bucket that holds Terraform state for this account.
# It is created outside Terraform (a state bucket can't hold its own state) with the same
# security defaults as every other bucket. Safe to rerun.
set -euo pipefail
PROFILE="${AWS_PROFILE:-gridpulse}"
REGION="${AWS_REGION:-us-east-1}"
ACCOUNT=$(aws sts get-caller-identity --profile "$PROFILE" --query Account --output text)
BUCKET="gridpulse-tfstate-${ACCOUNT}"
aws_() { aws --profile "$PROFILE" --region "$REGION" "$@"; }

if aws_ s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
  echo "state bucket exists: $BUCKET"
else
  # us-east-1 must not pass a LocationConstraint.
  if [ "$REGION" = "us-east-1" ]; then
    aws_ s3api create-bucket --bucket "$BUCKET" >/dev/null
  else
    aws_ s3api create-bucket --bucket "$BUCKET" \
      --create-bucket-configuration LocationConstraint="$REGION" >/dev/null
  fi
  echo "created state bucket: $BUCKET"
fi
aws_ s3api put-public-access-block --bucket "$BUCKET" --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
aws_ s3api put-bucket-versioning --bucket "$BUCKET" --versioning-configuration Status=Enabled
aws_ s3api put-bucket-encryption --bucket "$BUCKET" --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
aws_ s3api put-bucket-policy --bucket "$BUCKET" --policy "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Sid\":\"DenyInsecureTransport\",\"Effect\":\"Deny\",\"Principal\":\"*\",\"Action\":\"s3:*\",\"Resource\":[\"arn:aws:s3:::${BUCKET}\",\"arn:aws:s3:::${BUCKET}/*\"],\"Condition\":{\"Bool\":{\"aws:SecureTransport\":\"false\"}}}]}"
aws_ s3api put-bucket-tagging --bucket "$BUCKET" --tagging 'TagSet=[{Key=project,Value=gridpulse},{Key=gridpulse:lifecycle,Value=persistent}]'
echo "state bucket ready: $BUCKET (versioned, encrypted, private, TLS-only)"
