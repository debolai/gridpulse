# GitHub Actions -> AWS without stored keys (blueprint: github_oidc). GitHub signs a short-lived
# token per job; AWS trades it for a role's credentials only if the token says it comes from
# this repository, from the right kind of event.
#
# Three roles, by what the job is and where it runs (the token's `sub` claim):
# - ci (pull requests): read everything for `terraform plan`, and run dbt slim CI on Athena into
#   throwaway `ci_pr_<n>_*` databases. Pull requests from forks get no OIDC token from GitHub.
# - publish (pushes to main, no approval): push images to ECR, refresh the dbt manifest that
#   slim CI compares with.
# - deploy (jobs in the `production` environment, which requires the owner's approval):
#   `terraform apply` of the foundation stack and Helm deploys to the demo cluster (ADR-0009).

data "aws_caller_identity" "current" {}

locals {
  account  = data.aws_caller_identity.current.account_id
  ci_dbs   = "arn:aws:glue:${var.region}:${local.account}:database/ci_pr_*"
  ci_table = "arn:aws:glue:${var.region}:${local.account}:table/ci_pr_*/*"
  # Deleting a database also deletes its functions, so Glue checks those resources too.
  ci_udf = "arn:aws:glue:${var.region}:${local.account}:userDefinedFunction/ci_pr_*/*"
}

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

locals {
  subjects = {
    ci      = "${var.subject_prefix}:pull_request"
    publish = "${var.subject_prefix}:ref:refs/heads/main"
    deploy  = "${var.subject_prefix}:environment:production"
  }
}

data "aws_iam_policy_document" "trust" {
  for_each = local.subjects
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
      values   = [each.value]
    }
  }
}

resource "aws_iam_role" "ci" {
  name                 = "gridpulse-${var.env}-github-ci"
  description          = "GitHub Actions on pull requests: terraform plan (read-only) and dbt slim CI into ci_pr_* databases."
  assume_role_policy   = data.aws_iam_policy_document.trust["ci"].json
  max_session_duration = 3600
}

# `terraform plan` refreshes every resource, so it needs broad read access. Plans run with
# -lock=false, so the role never writes Terraform state.
resource "aws_iam_role_policy_attachment" "ci_read_only" {
  role       = aws_iam_role.ci.name
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}

data "aws_iam_policy_document" "ci" {
  # ReadOnlyAccess includes reading parameter values; nothing in CI needs this account's
  # secrets. AWS's public parameters (/aws/service/..., e.g. the EKS node AMI the compute plan
  # looks up) have no account in their ARN, so they stay readable.
  statement {
    sid       = "NoOwnParameters"
    effect    = "Deny"
    actions   = ["ssm:GetParameter*"]
    resources = ["arn:aws:ssm:*:${local.account}:parameter/*"]
  }
  statement {
    sid       = "NoSecrets"
    effect    = "Deny"
    actions   = ["secretsmanager:GetSecretValue", "kms:Decrypt"]
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
      local.ci_udf,
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

# --- publish: pushes to main ---------------------------------------------------------------

resource "aws_iam_role" "publish" {
  name                 = "gridpulse-${var.env}-github-publish"
  description          = "GitHub Actions on pushes to main: push images to ECR, refresh the slim-CI dbt manifest."
  assume_role_policy   = data.aws_iam_policy_document.trust["publish"].json
  max_session_duration = 3600
}

data "aws_iam_policy_document" "publish" {
  statement {
    sid       = "EcrLogin"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }
  statement {
    sid = "EcrPush"
    actions = [
      "ecr:BatchCheckLayerAvailability", "ecr:BatchGetImage", "ecr:CompleteLayerUpload",
      "ecr:DescribeImages", "ecr:GetDownloadUrlForLayer", "ecr:InitiateLayerUpload",
      "ecr:PutImage", "ecr:UploadLayerPart",
    ]
    resources = ["arn:aws:ecr:${var.region}:${local.account}:repository/gridpulse/*"]
  }
  statement {
    sid       = "SlimCiState"
    actions   = ["s3:PutObject"]
    resources = ["arn:aws:s3:::${var.lake_bucket}/ci/dbt-state/*"]
  }
}

resource "aws_iam_role_policy" "publish" {
  name   = "publish"
  role   = aws_iam_role.publish.id
  policy = data.aws_iam_policy_document.publish.json
}

# --- deploy: the production environment (owner's approval) --------------------------------
# Applies the foundation stack, so it manages everything that stack owns: gridpulse-* buckets
# (incl. Terraform state), Glue, Athena workgroups, budgets, ECR, and the GitHub OIDC roles.
# Because it can change gridpulse-* IAM roles (its own included), treat it as admin-equivalent
# for this project: the guard is that only an approved `production` job can assume it.

resource "aws_iam_role" "deploy" {
  name                 = "gridpulse-${var.env}-github-deploy"
  description          = "GitHub Actions in the production environment (approved): terraform apply (foundation) and Helm deploys."
  assume_role_policy   = data.aws_iam_policy_document.trust["deploy"].json
  max_session_duration = 3600
}

resource "aws_iam_role_policy_attachment" "deploy_read_only" {
  role       = aws_iam_role.deploy.name
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}

data "aws_iam_policy_document" "deploy" {
  statement {
    sid     = "Buckets"
    actions = ["s3:*"]
    resources = [
      "arn:aws:s3:::gridpulse-*",
      "arn:aws:s3:::gridpulse-*/*",
    ]
  }
  statement {
    sid       = "Catalog"
    actions   = ["glue:*"]
    resources = ["arn:aws:glue:${var.region}:${local.account}:*"]
  }
  statement {
    sid       = "Workgroups"
    actions   = ["athena:*"]
    resources = ["arn:aws:athena:${var.region}:${local.account}:workgroup/gridpulse-*"]
  }
  statement {
    sid       = "Budgets"
    actions   = ["budgets:*"]
    resources = ["arn:aws:budgets::${local.account}:budget/*"]
  }
  statement {
    sid       = "Registry"
    actions   = ["ecr:*"]
    resources = ["arn:aws:ecr:${var.region}:${local.account}:repository/gridpulse/*"]
  }
  statement {
    sid       = "RegistryLogin"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }
  statement {
    sid = "GithubRoles"
    actions = [
      "iam:CreateRole", "iam:DeleteRole", "iam:UpdateRole", "iam:UpdateAssumeRolePolicy",
      "iam:TagRole", "iam:UntagRole", "iam:PutRolePolicy", "iam:DeleteRolePolicy",
      "iam:AttachRolePolicy", "iam:DetachRolePolicy",
    ]
    resources = ["arn:aws:iam::${local.account}:role/gridpulse-*"]
  }
  statement {
    sid = "GithubProvider"
    actions = [
      "iam:CreateOpenIDConnectProvider", "iam:DeleteOpenIDConnectProvider",
      "iam:UpdateOpenIDConnectProviderThumbprint", "iam:AddClientIDToOpenIDConnectProvider",
      "iam:RemoveClientIDFromOpenIDConnectProvider", "iam:TagOpenIDConnectProvider",
      "iam:UntagOpenIDConnectProvider",
    ]
    resources = ["arn:aws:iam::${local.account}:oidc-provider/token.actions.githubusercontent.com"]
  }
  statement {
    sid       = "DemoCluster"
    actions   = ["eks:DescribeCluster"]
    resources = ["arn:aws:eks:${var.region}:${local.account}:cluster/gridpulse-*"]
  }
}

resource "aws_iam_role_policy" "deploy" {
  name   = "deploy"
  role   = aws_iam_role.deploy.id
  policy = data.aws_iam_policy_document.deploy.json
}
