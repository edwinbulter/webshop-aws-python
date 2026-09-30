variable "bus_name" {
  type        = string
  description = "Name of the custom EventBridge event bus."
}

variable "rules" {
  type = map(object({
    event_pattern = string
    target_arn    = string
  }))
  description = "Map of rule name => event pattern (JSON string) and target ARN."
}
