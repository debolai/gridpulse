output "buckets" {
  description = "Lake bucket names."
  value       = module.lake.bucket_names
}

output "glue_databases" {
  description = "Glue databases."
  value       = module.catalog.database_names
}

output "athena_workgroups" {
  description = "Athena workgroups."
  value       = module.catalog.workgroup_names
}

output "ecr_repositories" {
  description = "ECR repository URL per component."
  value       = module.ecr.repository_urls
}

output "github_ci_role_arn" {
  description = "Role GitHub Actions assumes on pull requests (repository variable AWS_CI_ROLE_ARN)."
  value       = module.github_oidc.ci_role_arn
}
