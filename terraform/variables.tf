variable "aws_region" {
  type    = string
  default = "eu-west-1"
}

variable "table_name" {
  type    = string
  default = "WebshopTable"
}

variable "event_bus_name" {
  type    = string
  default = "webshop-event-bus"
}

variable "flask_secret_key" {
  type        = string
  sensitive   = true
  description = "Signs the cart session cookie. Provide via -var, a .tfvars file that is gitignored, or a secrets manager reference -- never commit a real value."
}
