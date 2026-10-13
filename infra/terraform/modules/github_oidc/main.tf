# GitHub Actions -> AWS without stored keys (blueprint: github_oidc). GitHub signs a short-lived
# token per job; AWS trades it for a role's credentials only if the token says it comes from
# this repository, from the right kind of event.
#
# CI role (pull requests): read everything for `terraform plan`, and run dbt slim CI on Athena
# into throwaway `ci_pr_<n>_*` databases. Pull requests from forks get no OIDC token from GitHub,
# so outside contributors can't assume it.

data "aws_caller_identity" "current" {}

locals {
  account  = data.aws_caller_identity.current.account_id
  ci_dbs   = "arn:aws:glue:${var.region}:${local.account}:database/ci_pr_*"
  ci_table = "arn:aws:glue:${var.region}:${local.account}:table/ci_pr_*/*"
}

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

data "aws_iam_policy_document" "ci_trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.repository}:pull_request"]
    }
  }
}

resource "aws_iam_role" "ci" {
  name                 = "gridpulse-${var.env}-github-ci"
  description          = "GitHub Actions on pull requests: terraform plan (read-only) and dbt slim CI into ci_pr_* databases."
  assume_role_policy   = data.aws_iam_policy_document.ci_trust.json
  max_session_duration = 3600
}

# `terraform plan` refreshes every resource, so it needs broad read access. Plans run with
# -lock=false, so the role never writes Terraform state.
resource "aws_iam_role_policy_attachment" "ci_read_only" {
  role       = aws_iam_role.ci.name
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}

data "aws_iam_policy_document" "ci" {
  # ReadOnlyAccess includes reading parameter values; nothing in CI needs secrets.
  statement {
    sid       = "NoSecrets"
    effect    = "Deny"
    actions   = ["ssm:GetParameter*", "secretsmanager:GetSecretValue", "kms:Decrypt"]
    resources = ["*"]
  }
  statement {
    sid = "AthenaQueries"
    actions = [
      "athena:StartQueryExecution", "athena:GetQueryExecution", "athena:GetQueryResults",
      "athena:StopQueryExecution", "athena:GetWorkGroup",
    ]
    resources = ["arn:aws:athena:${var.region}:${local.account}:workgroup/${var.athena_workgroup}"]
  }
  # dbt reads unchanged models from the real databases (deferral) and builds changed ones
  # into ci_pr_<n>_* databases, which pr-cleanup drops.
  statement {
    sid = "GlueCiDatabases"
    actions = [
      "glue:CreateDatabase", "glue:DeleteDatabase", "glue:UpdateDatabase",
      "glue:CreateTable", "glue:UpdateTable", "glue:DeleteTable", "glue:BatchDeleteTable",
      "glue:CreatePartition", "glue:BatchCreatePartition", "glue:DeletePartition",
      "glue:BatchDeletePartition", "glue:UpdatePartition",
    ]
    resources = [
      "arn:aws:glue:${var.region}:${local.account}:catalog",
      local.ci_dbs,
      local.ci_table,
    ]
  }
  statement {
    sid       = "CiData"
    actions   = ["s3:PutObject", "s3:DeleteObject", "s3:AbortMultipartUpload"]
    resources = ["arn:aws:s3:::${var.lake_bucket}/dbt/ci_pr_*"]
  }
  statement {
    sid       = "AthenaResults"
    actions   = ["s3:PutObject", "s3:AbortMultipartUpload"]
    resources = ["arn:aws:s3:::${var.athena_results_bucket}/*"]
  }
}

resource "aws_iam_role_policy" "ci" {
  name   = "slim-ci"
  role   = aws_iam_role.ci.id
  policy = data.aws_iam_policy_document.ci.json
}
