terraform {
  required_version = ">= 1.10" # native S3 state locking

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.60"
    }
  }

  # Partial config: bucket name includes the account ID, so `make tf-init` passes it.
  backend "s3" {
    key          = "dev/foundation.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      project               = "gridpulse"
      env                   = var.env
      "gridpulse:lifecycle" = "persistent"
      managed_by            = "terraform"
    }
  }
}
