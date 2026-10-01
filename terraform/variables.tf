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

variable "github_owner_id" {
  type        = string
  default     = "160537673"
  description = "GitHub's immutable numeric id for this repo's owner (github.com/edwinbulter) -- look up via `gh api repos/edwinbulter/webshop-aws-python --jq .owner.id`. See terraform/modules/github_oidc/variables.tf for why this, not the login name, is what the OIDC trust policy matches on."
}

variable "github_repo_id" {
  type        = string
  default     = "1397936988"
  description = "GitHub's immutable numeric id for this repo -- look up via `gh api repos/edwinbulter/webshop-aws-python --jq .id`."
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

