output "cluster_name" {
  description = "EKS cluster name."
  value       = module.eks.cluster_name
}

output "region" {
  description = "AWS region."
  value       = var.region
}

output "workload_roles" {
  description = "IAM role ARN per workload service account."
  value       = { for k, r in aws_iam_role.workload : k => r.arn }
}
