variable "env" {
  description = "Environment name (e.g. dev)."
  type        = string
}

variable "region" {
  description = "AWS region."
  type        = string
}

variable "repository" {
  description = "GitHub repository allowed to assume the roles, as owner/name."
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
