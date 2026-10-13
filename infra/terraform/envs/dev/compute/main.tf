# Demo-window compute for GridPulse: VPC, EKS (Spot, Graviton) and workload IAM roles.
# Created by `make aws-up`, destroyed by `make aws-down`. The data layer (buckets, Glue,
# Athena, ECR) lives in ../foundation and is untouched by this stack.

data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_caller_identity" "current" {}

locals {
  name    = "gridpulse-${var.env}"
  azs     = slice(data.aws_availability_zones.available.names, 0, 2)
  account = data.aws_caller_identity.current.account_id
  buckets = {
    raw     = "gridpulse-${var.env}-raw"
    lake    = "gridpulse-${var.env}-lake"
    results = "gridpulse-${var.env}-athena-results"
  }
}

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "6.7.3"

  name = local.name
  cidr = "10.40.0.0/16"
  azs  = local.azs

  private_subnets = ["10.40.0.0/20", "10.40.16.0/20"]
  public_subnets  = ["10.40.128.0/24", "10.40.129.0/24"]

  # One NAT gateway: cheaper than one per AZ, acceptable for a demo cluster.
  enable_nat_gateway   = true
  single_nat_gateway   = true
  enable_dns_hostnames = true

  public_subnet_tags  = { "kubernetes.io/role/elb" = 1 }
  private_subnet_tags = { "kubernetes.io/role/internal-elb" = 1 }
}

# S3 traffic (Athena results, lake reads) skips the NAT gateway: gateway endpoints are free.
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = module.vpc.vpc_id
  service_name      = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = module.vpc.private_route_table_ids
}

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "21.29.0"

  name               = local.name
  kubernetes_version = var.kubernetes_version

  endpoint_public_access       = true
  endpoint_public_access_cidrs = var.api_access_cidrs

  # The SSO admin role that runs `make aws-up` gets cluster-admin via an EKS access entry.
  enable_cluster_creator_admin_permissions = true

  # CD (GitHub, production environment) deploys with Helm into the gridpulse namespace only.
  access_entries = {
    github_deploy = {
      principal_arn = "arn:aws:iam::${local.account}:role/gridpulse-${var.env}-github-deploy"
      policy_associations = {
        gridpulse = {
          policy_arn = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSAdminPolicy"
          access_scope = {
            type       = "namespace"
            namespaces = ["gridpulse"]
          }
        }
      }
    }
  }

  # Demo cluster, recreated often: no customer-managed KMS key (each would linger 7+ days after
  # destroy, pending deletion) and no control-plane log group. EKS still encrypts secrets at
  # rest by default with an AWS-owned key.
  create_kms_key              = false
  encryption_config           = null
  enabled_log_types           = []
  create_cloudwatch_log_group = false

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  addons = {
    coredns    = {}
    kube-proxy = {}
    vpc-cni = {
      before_compute = true
    }
    eks-pod-identity-agent = {
      before_compute = true
    }
  }

  eks_managed_node_groups = {
    spot = {
      ami_type       = "AL2023_ARM_64_STANDARD"
      instance_types = var.node_instance_types
      capacity_type  = "SPOT"
      min_size       = 1
      max_size       = 3
      desired_size   = 2
    }
  }
}
