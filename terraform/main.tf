locals {
  repo_root = abspath("${path.module}/..")

  queue_names = {
    payment      = "payment-service-queue"
    inventory    = "inventory-service-queue"
    notification = "notification-service-queue"
  }

  base_event_pattern = {
    source        = ["webshop.orders"]
    "detail-type" = ["OrderPlaced"]
  }
}

# Created once, out-of-band, via `aws ssm put-parameter` (see README) -- read
# only, never managed here, so a human's local apply and CI's apply always
# resolve the exact same live secret instead of two independently-set copies
# that could silently drift apart.
data "aws_ssm_parameter" "flask_secret_key" {
  name            = var.flask_secret_key_ssm_parameter_name
  with_decryption = true
}

module "dynamodb" {
  source     = "./modules/dynamodb"
  table_name = var.table_name
}

module "cognito" {
  source = "./modules/cognito"
}

module "sqs" {
  source            = "./modules/sqs"
  queue_names       = values(local.queue_names)
  dlq_name          = "webshop-dlq"
  max_receive_count = 3
}

module "eventbridge" {
  source   = "./modules/eventbridge"
  bus_name = var.event_bus_name

  rules = {
    "payment-rule" = {
      event_pattern = jsonencode(local.base_event_pattern)
      target_arn    = module.sqs.queue_arns[local.queue_names.payment]
    }
    "inventory-rule" = {
      event_pattern = jsonencode(local.base_event_pattern)
      target_arn    = module.sqs.queue_arns[local.queue_names.inventory]
    }
    "notification-rule" = {
      event_pattern = jsonencode(merge(local.base_event_pattern, {
        detail = { notify = [true] }
      }))
      target_arn = module.sqs.queue_arns[local.queue_names.notification]
    }
  }
}

# aws_cloudwatch_event_target does not implicitly grant the rule permission to
# send to the queue -- each queue needs an explicit policy scoped to the rule
# that targets it, or delivery silently fails.
resource "aws_sqs_queue_policy" "allow_eventbridge" {
  for_each = {
    (local.queue_names.payment)      = "payment-rule"
    (local.queue_names.inventory)    = "inventory-rule"
    (local.queue_names.notification) = "notification-rule"
  }

  queue_url = module.sqs.queue_urls[each.key]

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowEventBridgePut"
      Effect    = "Allow"
      Principal = { Service = "events.amazonaws.com" }
      Action    = "sqs:SendMessage"
      Resource  = module.sqs.queue_arns[each.key]
      Condition = {
        ArnEquals = { "aws:SourceArn" = module.eventbridge.rule_arns[each.value] }
      }
    }]
  })
}

module "lambda_main_app" {
  source               = "./modules/lambda"
  function_name        = "webshop-main-app"
  handler              = "app.main.handler"
  repo_root            = local.repo_root
  source_paths         = ["app"]
  install_dependencies = true

  environment_variables = {
    TABLE_NAME            = module.dynamodb.table_name
    GSI1_NAME             = "GSI1"
    GSI2_NAME             = "GSI2"
    EVENT_BUS_NAME        = module.eventbridge.bus_name
    SECRET_KEY            = data.aws_ssm_parameter.flask_secret_key.value
    COGNITO_USER_POOL_ID  = module.cognito.user_pool_id
    COGNITO_CLIENT_ID     = module.cognito.client_id
    COGNITO_CLIENT_SECRET = module.cognito.client_secret
  }

  iam_policy_statements = [
    {
      actions = [
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:UpdateItem",
        "dynamodb:DeleteItem",
        "dynamodb:Query",
        "dynamodb:BatchWriteItem",
      ]
      resources = [module.dynamodb.table_arn, "${module.dynamodb.table_arn}/index/*"]
    },
    {
      actions   = ["events:PutEvents"]
      resources = [module.eventbridge.bus_arn]
    },
    {
      # User-facing Cognito calls (SignUp, InitiateAuth, ForgotPassword, ...)
      # are authorized by the app client id/secret + the caller's own token,
      # not by IAM -- they need no statement here at all. Only the Admin*/
      # List* calls are IAM-gated.
      actions = [
        "cognito-idp:AdminListGroupsForUser",
        "cognito-idp:AdminGetUser",
        "cognito-idp:AdminUpdateUserAttributes",
        "cognito-idp:ListUsers",
      ]
      resources = [module.cognito.user_pool_arn]
    },
  ]
}

module "lambda_payment_service" {
  source        = "./modules/lambda"
  function_name = "webshop-payment-service"
  handler       = "consumers.payment_service.handler.handler"
  repo_root     = local.repo_root
  source_paths  = ["app", "consumers"]

  environment_variables = {
    TABLE_NAME = module.dynamodb.table_name
    GSI1_NAME  = "GSI1"
  }

  iam_policy_statements = [
    { actions = ["dynamodb:UpdateItem"], resources = [module.dynamodb.table_arn] },
  ]

  has_sqs_trigger       = true
  sqs_trigger_queue_arn = module.sqs.queue_arns[local.queue_names.payment]
}

module "lambda_inventory_service" {
  source        = "./modules/lambda"
  function_name = "webshop-inventory-service"
  handler       = "consumers.inventory_service.handler.handler"
  repo_root     = local.repo_root
  source_paths  = ["app", "consumers"]

  environment_variables = {
    TABLE_NAME = module.dynamodb.table_name
    GSI1_NAME  = "GSI1"
  }

  iam_policy_statements = [
    { actions = ["dynamodb:UpdateItem"], resources = [module.dynamodb.table_arn] },
  ]

  has_sqs_trigger       = true
  sqs_trigger_queue_arn = module.sqs.queue_arns[local.queue_names.inventory]
}

module "lambda_notification_service" {
  source        = "./modules/lambda"
  function_name = "webshop-notification-service"
  handler       = "consumers.notification_service.handler.handler"
  repo_root     = local.repo_root
  source_paths  = ["app", "consumers"]

  environment_variables = {
    TABLE_NAME = module.dynamodb.table_name
    GSI1_NAME  = "GSI1"
  }

  iam_policy_statements = [
    { actions = ["dynamodb:UpdateItem"], resources = [module.dynamodb.table_arn] },
  ]

  has_sqs_trigger       = true
  sqs_trigger_queue_arn = module.sqs.queue_arns[local.queue_names.notification]
}

module "api_gateway" {
  source               = "./modules/api_gateway"
  api_name             = "webshop-api"
  lambda_function_name = module.lambda_main_app.function_name
  lambda_invoke_arn    = module.lambda_main_app.invoke_arn
}

module "custom_domain" {
  source      = "./modules/custom_domain"
  domain_name = var.domain_name
  root_domain = var.root_domain
  api_id      = module.api_gateway.api_id
  stage       = "$default"
}

module "github_oidc" {
  source               = "./modules/github_oidc"
  github_owner_id      = var.github_owner_id
  github_repo_id       = var.github_repo_id
  github_environment   = var.github_environment
  create_oidc_provider = var.create_github_oidc_provider
  lambda_function_arns = [
    module.lambda_main_app.function_arn,
    module.lambda_payment_service.function_arn,
    module.lambda_inventory_service.function_arn,
    module.lambda_notification_service.function_arn,
  ]
}
