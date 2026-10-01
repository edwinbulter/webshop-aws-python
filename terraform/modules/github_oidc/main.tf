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
          "token.actions.githubusercontent.com:sub" = "repo:${var.github_org}/${var.github_repo}:environment:${var.github_environment}"
        }
      }
    }]
  })
}

# Two enforcement layers exist for "this pipeline may only redeploy Lambda
# code": the workflow's own `-target` flags (blast-radius/plan-output
# hygiene -- keeps unrelated resources out of the graph) and this policy
# (the actual hard boundary -- AWS rejects anything beyond what's listed
# here with AccessDenied, regardless of what the workflow or its target
# list ever try to do).
resource "aws_iam_role_policy" "deploy" {
  name = "webshop-aws-python-github-deploy"
  role = aws_iam_role.deploy.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "TerraformStateObject"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject"]
        Resource = "${var.state_bucket_arn}/${var.state_object_key}"
      },
      {
        Sid      = "TerraformStateBucketList"
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = var.state_bucket_arn
      },
      {
        Sid      = "TerraformStateLock"
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem"]
        Resource = var.lock_table_arn
      },
      {
        Sid    = "ReadOnlyForPlan"
        Effect = "Allow"
        Action = [
          "route53:GetHostedZone",
          "route53:ListResourceRecordSets",
          "acm:DescribeCertificate",
          "acm:ListCertificates",
          "cognito-idp:DescribeUserPool",
          "cognito-idp:DescribeUserPoolClient",
          "cognito-idp:ListGroups",
          "cognito-idp:ListTagsForResource",
          "dynamodb:DescribeTable",
          "sqs:GetQueueAttributes",
          "sqs:GetQueueUrl",
          "events:DescribeEventBus",
          "events:DescribeRule",
          "events:ListTargetsByRule",
          "iam:GetRole",
          "iam:GetRolePolicy",
          "iam:ListRolePolicies",
          "iam:ListAttachedRolePolicies",
          "apigateway:GET",
          "logs:DescribeLogGroups",
          "lambda:GetFunction",
          "lambda:GetFunctionConfiguration",
          "lambda:ListVersionsByFunction",
        ]
        Resource = "*"
      },
      {
        Sid      = "SecretLookup"
        Effect   = "Allow"
        Action   = ["ssm:GetParameter"]
        Resource = var.ssm_parameter_arn
      },
      {
        # The default alias/aws/ssm KMS key has no fixed ARN to scope to
        # without an extra lookup; acceptable at this project's scale.
        Sid      = "SecretDecrypt"
        Effect   = "Allow"
        Action   = ["kms:Decrypt"]
        Resource = "*"
      },
      {
        Sid      = "DeployLambdaCodeOnly"
        Effect   = "Allow"
        Action   = ["lambda:UpdateFunctionCode", "lambda:TagResource", "lambda:UntagResource"]
        Resource = var.lambda_function_arns
      },
    ]
  })
}
