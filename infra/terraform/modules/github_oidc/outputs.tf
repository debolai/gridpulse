output "ci_role_arn" {
  description = "Role GitHub Actions assumes on pull requests."
  value       = aws_iam_role.ci.arn
}

output "oidc_provider_arn" {
  description = "GitHub's OIDC identity provider in this account."
  value       = aws_iam_openid_connect_provider.github.arn
}
