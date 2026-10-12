terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.60"
    }
  }

  # Separate state from the foundation: destroying compute can never touch the data layer.
  backend "s3" {
    key          = "dev/compute.tfstate"
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
      "gridpulse:lifecycle" = "ephemeral" # make aws-down checks nothing with this tag survives
      managed_by            = "terraform"
    }
  }
}
