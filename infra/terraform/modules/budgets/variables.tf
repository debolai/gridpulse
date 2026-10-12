variable "monthly_limit_usd" {
  description = "Monthly budget in USD. Alerts fire at 50% and 100% of it."
  type        = number
  default     = 50
}

variable "alert_email" {
  description = "Address that receives budget alerts."
  type        = string
}
