terraform {
  required_version = ">= 1.5.0"

  # Bucket/key/region/dynamodb_table are intentionally not hardcoded here --
  # pass them via `terraform init -backend-config=...` (see README's
  # "Deployment naar AWS" section) so no account-specific values live in
  # version control. Bootstrapped once, out-of-band, via AWS CLI: Terraform
  # cannot create its own backend before it has one.
  backend "s3" {}

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.79"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.6"
    }
    null = {
      source  = "hashicorp/null"
      version = "~> 3.2"
    }
  }
}

provider "aws" {
  region = var.aws_region
}
