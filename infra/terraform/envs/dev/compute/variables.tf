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

variable "kubernetes_version" {
  description = "EKS Kubernetes version (one behind the newest, for add-on compatibility)."
  type        = string
  default     = "1.36"
}

variable "node_instance_types" {
  description = "Graviton (arm64) Spot instance types; several types improve Spot availability."
  type        = list(string)
  default     = ["t4g.large", "m7g.large", "m6g.large"]
}

variable "api_access_cidrs" {
  description = "CIDRs allowed to reach the EKS API endpoint (kubectl). Auth is still IAM."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}
