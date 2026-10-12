output "repository_urls" {
  description = "Repository URL per component."
  value       = { for k, r in aws_ecr_repository.this : k => r.repository_url }
}
