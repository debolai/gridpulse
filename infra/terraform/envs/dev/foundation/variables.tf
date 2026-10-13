variable "env" {
  description = "Environment name."
  type        = string
  default     = "dev"
}

variable "region" {
  description = "AWS region."
  type        = string
  default     = "us-east-1"
}

variable "budget_alert_email" {
  description = "Email for AWS Budgets alerts."
  type        = string
}

variable "monthly_budget_usd" {
  description = "Monthly budget in USD (alerts at 50% and 100%)."
  type        = number
  default     = 50
}

variable "github_repository" {
  description = "GitHub repository (owner/name) whose Actions may assume the CI and deploy roles."
  type        = string
  default     = "debolai/gridpulse"
}
