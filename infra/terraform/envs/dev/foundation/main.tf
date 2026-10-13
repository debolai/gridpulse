# Always-on foundation for the dev environment: costs cents to a few dollars a month and
# holds the data, so it stays up while compute (EKS, RDS, NAT) is created only for demos.
# GitHub OIDC (B5) lets GitHub Actions use short-lived roles instead of stored keys.

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

module "ecr" {
  source     = "../../../modules/ecr"
  components = ["ingestion", "transform", "semantic", "agent"]
}

module "github_oidc" {
  source                = "../../../modules/github_oidc"
  env                   = var.env
  region                = var.region
  subject_prefix        = var.github_subject_prefix
  lake_bucket           = module.lake.bucket_names["lake"]
  athena_results_bucket = module.lake.bucket_names["athena_results"]
  athena_workgroup      = "gridpulse-${var.env}"
}
