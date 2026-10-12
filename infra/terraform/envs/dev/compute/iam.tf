# One IAM role per workload, granted to its Kubernetes service account through EKS Pod Identity.
# No access keys anywhere: pods get short-lived credentials for exactly these permissions.

data "aws_iam_policy_document" "pod_identity_trust" {
  statement {
    actions = ["sts:AssumeRole", "sts:TagSession"]
    principals {
      type        = "Service"
      identifiers = ["pods.eks.amazonaws.com"]
    }
  }
}

# Semantic API: run Athena queries in its workgroup, read the catalog and lake, write results.
data "aws_iam_policy_document" "semantic" {
  statement {
    sid = "Athena"
    actions = [
      "athena:StartQueryExecution", "athena:GetQueryExecution", "athena:GetQueryResults",
      "athena:StopQueryExecution", "athena:GetWorkGroup", "athena:ListQueryExecutions",
    ]
    resources = ["arn:aws:athena:${var.region}:${local.account}:workgroup/gridpulse-${var.env}*"]
  }
  statement {
    sid       = "GlueRead"
    actions   = ["glue:GetDatabase", "glue:GetDatabases", "glue:GetTable", "glue:GetTables", "glue:GetPartition", "glue:GetPartitions"]
    resources = ["arn:aws:glue:${var.region}:${local.account}:*"]
  }
  statement {
    sid       = "LakeRead"
    actions   = ["s3:GetObject", "s3:ListBucket", "s3:GetBucketLocation"]
    resources = flatten([for b in [local.buckets.raw, local.buckets.lake] : ["arn:aws:s3:::${b}", "arn:aws:s3:::${b}/*"]])
  }
  statement {
    sid       = "AthenaResults"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:ListBucket", "s3:GetBucketLocation", "s3:AbortMultipartUpload"]
    resources = ["arn:aws:s3:::${local.buckets.results}", "arn:aws:s3:::${local.buckets.results}/*"]
  }
}

# Agent: call Claude on Bedrock (cross-region inference profiles fan out to several regions).
data "aws_iam_policy_document" "agent" {
  statement {
    sid     = "InvokeClaude"
    actions = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = [
      "arn:aws:bedrock:${var.region}:${local.account}:inference-profile/us.anthropic.*",
      "arn:aws:bedrock:*::foundation-model/anthropic.*",
    ]
  }
}

locals {
  workloads = {
    semantic = data.aws_iam_policy_document.semantic.json
    agent    = data.aws_iam_policy_document.agent.json
  }
}

resource "aws_iam_role" "workload" {
  for_each           = local.workloads
  name               = "${local.name}-${each.key}"
  assume_role_policy = data.aws_iam_policy_document.pod_identity_trust.json
}

resource "aws_iam_role_policy" "workload" {
  for_each = local.workloads
  name     = each.key
  role     = aws_iam_role.workload[each.key].id
  policy   = each.value
}

resource "aws_eks_pod_identity_association" "workload" {
  for_each        = local.workloads
  cluster_name    = module.eks.cluster_name
  namespace       = "gridpulse"
  service_account = each.key
  role_arn        = aws_iam_role.workload[each.key].arn
}
