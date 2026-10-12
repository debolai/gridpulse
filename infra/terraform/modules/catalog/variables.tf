variable "env" {
  description = "Environment name (e.g. dev)."
  type        = string
}

variable "raw_bucket" {
  description = "Raw bucket name (raw Iceberg tables)."
  type        = string
}

variable "lake_bucket" {
  description = "Lake bucket name (dbt-built layers)."
  type        = string
}

variable "athena_results_bucket" {
  description = "Bucket for Athena query results."
  type        = string
}

variable "query_scan_limit_bytes" {
  description = "Per-query scan cutoff for the main workgroup (Athena minimum is 10 MB)."
  type        = number
  default     = 1073741824 # 1 GB
}

variable "agent_scan_limit_bytes" {
  description = "Per-query scan cutoff for the LLM agent's workgroup."
  type        = number
  default     = 209715200 # 200 MB
}
