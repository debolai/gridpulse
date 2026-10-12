# Always-on foundation for the dev environment: costs cents to a few dollars a month and
# holds the data, so it stays up while compute (EKS, RDS, NAT) is created only for demos.
# ECR, IAM workload roles, GitHub OIDC and SSM parameters join in phase A6.

module "lake" {
  source = "../../../modules/lake"
  env    = var.env
}

module "catalog" {
  source                = "../../../modules/catalog"
  env                   = var.env
  raw_bucket            = module.lake.bucket_names["raw"]
  lake_bucket           = module.lake.bucket_names["lake"]
  athena_results_bucket = module.lake.bucket_names["athena_results"]
}

module "budgets" {
  source            = "../../../modules/budgets"
  alert_email       = var.budget_alert_email
  monthly_limit_usd = var.monthly_budget_usd
}
