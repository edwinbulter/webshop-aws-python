variable "github_owner_id" {
  type        = string
  description = "GitHub's immutable numeric id for the repo owner (not the org/user login, which can be renamed) -- see https://api.github.com/repos/<owner>/<repo> -> .owner.id. Used in the trust policy instead of the owner name because repos created after 2026-07-15 get GitHub's \"immutable subject claims\", whose sub embeds this id rather than (or alongside, but unmatchable by name alone) the current name."
}

variable "github_repo_id" {
  type        = string
  description = "GitHub's immutable numeric id for the repo itself (not its name, which can be renamed) -- see https://api.github.com/repos/<owner>/<repo> -> .id. Same reasoning as github_owner_id."
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

variable "lambda_function_arns" {
  type        = list(string)
  description = "The 4 Lambda function ARNs this role is allowed to update the code of -- and nothing else."
}
