output "queue_arns" {
  value = { for name, q in aws_sqs_queue.this : name => q.arn }
}

output "queue_urls" {
  value = { for name, q in aws_sqs_queue.this : name => q.id }
}

output "dlq_arn" {
  value = aws_sqs_queue.dlq.arn
}
