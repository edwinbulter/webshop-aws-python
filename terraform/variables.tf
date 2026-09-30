variable "aws_region" {
  type        = string
  description = "No default on purpose: this must always come from terraform/backend.env's AWS_REGION (via TF_VAR_aws_region), the single source of truth for which region this deploys to -- never hardcode a region literal anywhere else in this project."
}

variable "table_name" {
  type    = string
  default = "WebshopTable"
}

variable "event_bus_name" {
  type    = string
  default = "webshop-event-bus"
}

variable "domain_name" {
  type        = string
  default     = "webshop-aws-python.kabulter.click"
  description = "FQDN for the live demo."
}

variable "root_domain" {
  type        = string
  default     = "kabulter.click"
  description = "Existing Route53 hosted zone name. Looked up as a data source only; this project never creates, modifies, or destroys the zone itself, only records within it for domain_name."
}

variable "flask_secret_key_ssm_parameter_name" {
  type        = string
  default     = "/webshop-aws-python/flask-secret-key"
  description = "Path of the pre-existing SSM SecureString parameter holding the Flask session-cookie secret. Created once out-of-band via `aws ssm put-parameter` (see README) -- Terraform only reads it, so both a human's local apply and CI's apply always resolve the same live value."
}

variable "github_org" {
  type    = string
  default = "edwinbulter"
}

variable "github_repo" {
  type    = string
  default = "webshop-aws-python"
}

variable "github_environment" {
  type        = string
  default     = "production"
  description = "GitHub Environment the deploy workflow runs under. Configure a required reviewer on this Environment in the GitHub repo settings to turn the manually-triggered deploy into a manually-triggered-and-approved one."
}

variable "create_github_oidc_provider" {
  type        = bool
  default     = false
  description = "False by default: this AWS account already has a token.actions.githubusercontent.com OIDC provider from another project (only one can exist per account per URL, confirmed via a failed CreateOpenIDConnectProvider/EntityAlreadyExists on the first real apply). Set to true only for a from-scratch account that doesn't have one yet."
}

variable "tf_state_bucket_name" {
  type        = string
  default     = "edwinbulter-terraform-state"
  description = "Name of the S3 bucket used for the Terraform backend. Shared across other applications' state too -- bootstrapped (created only if missing) via scripts/bootstrap_terraform_backend.sh, never modified here. Must match the `bucket` value passed to `terraform init -backend-config`."
}

variable "tf_state_key" {
  type        = string
  default     = "webshop-aws-python/terraform.tfstate"
  description = "This app's own state path within the shared backend bucket. Must match the `key` value passed to `terraform init -backend-config`."
}

variable "tf_state_lock_table_name" {
  type        = string
  default     = "terraform-locks"
  description = "Name of the DynamoDB table used for Terraform state locking. Shared across applications (one lock item per app, keyed by its bucket+key path) -- bootstrapped (created only if missing) via scripts/bootstrap_terraform_backend.sh. Must match the `dynamodb_table` value passed to `terraform init -backend-config`."
}
