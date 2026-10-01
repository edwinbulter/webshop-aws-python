data "aws_iam_openid_connect_provider" "github" {
  count = var.create_oidc_provider ? 0 : 1
  url   = "https://token.actions.githubusercontent.com"
}

# AWS validates GitHub's actual TLS chain directly for this well-known
# provider; the thumbprint value itself is no longer security-relevant, but
# the argument is still required by the resource schema.
resource "aws_iam_openid_connect_provider" "github" {
  count = var.create_oidc_provider ? 1 : 0

  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}

locals {
  oidc_provider_arn = var.create_oidc_provider ? aws_iam_openid_connect_provider.github[0].arn : data.aws_iam_openid_connect_provider.github[0].arn
}

resource "aws_iam_role" "deploy" {
  name = "webshop-aws-python-github-deploy"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = local.oidc_provider_arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        }
        # StringLike (not StringEquals) on purpose, pinned to the *numeric*
        # owner/repo IDs rather than their names: repos created on GitHub
        # after 2026-07-15 get "immutable subject claims" by default, whose
        # sub is "repo:<owner_name>@<owner_id>/<repo_name>@<repo_id>:environment:<env>"
        # (see https://github.blog/changelog/2026-04-23-immutable-subject-claims-for-github-actions-oidc-tokens/).
        # Matching StringEquals against the plain "repo:org/repo:environment:..."
        # format fails outright against that token with a bare AccessDenied on
        # sts:AssumeRoleWithWebIdentity -- there is no partial-match fallback.
        # Wildcarding the *names* and pinning the *ids* is also strictly safer
        # than matching on names: it survives a future org/repo rename (the id
        # never changes) and can't be satisfied by an attacker who deletes this
        # repo and recreates one with the same name (a fresh repo gets a new id).
        StringLike = {
          "token.actions.githubusercontent.com:sub" = "repo:*@${var.github_owner_id}/*@${var.github_repo_id}:environment:${var.github_environment}"
        }
      }
    }]
  })
}

# Deliberately the ONLY statement: this pipeline calls `aws lambda
# update-function-code` directly (no Terraform in deploy.yml at all -- that's
# a human, local-only action per README's "Deployment naar AWS"), so this
# role needs nothing beyond updating code on exactly these 4 functions and
# waiting for that update to finish. No state-bucket/lock-table access, no
# broad read-only "for plan" grant, no secrets access: all of that existed
# only because deploy.yml used to run a real `terraform apply`, which needed
# to refresh the whole resource graph even though it only ever touched these
# 4 functions. AWS rejects anything beyond what's listed here with
# AccessDenied, regardless of what the workflow ever tries to do.
resource "aws_iam_role_policy" "deploy" {
  name = "webshop-aws-python-github-deploy"
  role = aws_iam_role.deploy.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "DeployLambdaCodeOnly"
        Effect = "Allow"
        # GetFunction/GetFunctionConfiguration are for `aws lambda wait
        # function-updated` after each update-function-code call, not for
        # reading anything -- the deploy step doesn't branch on the response.
        Action   = ["lambda:UpdateFunctionCode", "lambda:GetFunction", "lambda:GetFunctionConfiguration"]
        Resource = var.lambda_function_arns
      },
    ]
  })
}
