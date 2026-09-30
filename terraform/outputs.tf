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
