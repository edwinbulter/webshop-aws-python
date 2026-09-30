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

output "github_deploy_role_arn" {
  value       = module.github_oidc.role_arn
  description = "Set this as the AWS_DEPLOY_ROLE_ARN repo Variable in GitHub so deploy.yml can assume it via OIDC."
}
