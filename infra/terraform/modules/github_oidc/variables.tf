variable "env" {
  description = "Environment name (e.g. dev)."
  type        = string
}

variable "region" {
  description = "AWS region."
  type        = string
}

variable "subject_prefix" {
  description = <<-EOT
    Start of the OIDC `sub` claim GitHub sends for this repository. This repository uses
    GitHub's immutable form, repo:<owner>@<owner id>/<repo>@<repo id> (see
    `gh api repos/<owner>/<repo>/actions/oidc/customization/sub`), so a renamed or re-created
    repository with the same name can't assume the roles.
  EOT
  type        = string
}

variable "lake_bucket" {
  description = "Lake bucket name (dbt-built layers; slim CI writes under dbt/ci_pr_*)."
  type        = string
}

variable "athena_results_bucket" {
  description = "Bucket for Athena query results."
  type        = string
}

variable "athena_workgroup" {
  description = "Athena workgroup slim CI runs dbt in."
  type        = string
}
