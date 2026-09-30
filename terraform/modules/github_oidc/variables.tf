variable "github_org" {
  type = string
}

variable "github_repo" {
  type = string
}

variable "github_environment" {
  type        = string
  description = "GitHub Environment name the deploy workflow runs under. The trust policy only allows AssumeRoleWithWebIdentity for workflow runs scoped to this environment, so configuring a required reviewer on it (in the GitHub UI) adds a manual-approval gate on top of workflow_dispatch."
}

variable "create_oidc_provider" {
  type        = bool
  default     = true
  description = "AWS allows only one OIDC provider per URL per account. Set to false if this account already has a token.actions.githubusercontent.com provider from another project; its ARN is then looked up instead of created."
}

variable "state_bucket_arn" {
  type        = string
  description = "ARN of the S3 bucket holding Terraform state (see backend config)."
}

variable "state_object_key" {
  type        = string
  description = "The state object's key within the bucket, e.g. webshop-aws-python/terraform.tfstate. Must match the backend config's `key`."
}

variable "lock_table_arn" {
  type        = string
  description = "ARN of the DynamoDB table used for Terraform state locking."
}

variable "ssm_parameter_arn" {
  type        = string
  description = "ARN of the SSM SecureString parameter holding the Flask secret key, so `terraform plan`/`apply` can resolve its data source."
}

variable "lambda_function_arns" {
  type        = list(string)
  description = "The 4 Lambda function ARNs this role is allowed to update the code of -- and nothing else."
}
