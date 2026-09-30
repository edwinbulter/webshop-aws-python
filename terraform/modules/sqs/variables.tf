variable "queue_names" {
  type        = list(string)
  description = "Names of the fan-out target queues (one per downstream consumer)."
}

variable "dlq_name" {
  type        = string
  description = "Name of the shared dead-letter queue used by all fan-out queues."
}

variable "max_receive_count" {
  type        = number
  default     = 3
  description = "Number of failed receives before a message is moved to the DLQ."
}
