output "api_endpoint" {
  value = module.api_gateway.api_endpoint
}

output "table_name" {
  value = module.dynamodb.table_name
}

output "event_bus_name" {
  value = module.eventbridge.bus_name
}

output "queue_urls" {
  value = module.sqs.queue_urls
}

output "live_url" {
  value = module.custom_domain.live_url
}

output "cognito_user_pool_id" {
  value       = module.cognito.user_pool_id
  description = "Used by the one-off `aws cognito-idp admin-create-user` bootstrap command for the fixed admin account (see README's Deployment naar AWS)."
}

output "github_deploy_role_arn" {
  value       = module.github_oidc.role_arn
  description = "Set this as the AWS_DEPLOY_ROLE_ARN repo Variable in GitHub so deploy.yml can assume it via OIDC."
}
