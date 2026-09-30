variable "domain_name" {
  type        = string
  description = "Full FQDN for the live demo, e.g. webshop-aws-python.kabulter.click."
}

variable "root_domain" {
  type        = string
  description = "The existing Route53 hosted zone name, e.g. kabulter.click. Looked up as a data source only -- never created or destroyed here."
}

variable "api_id" {
  type        = string
  description = "ID of the HTTP API (apigatewayv2) to map this domain onto."
}

variable "stage" {
  type        = string
  description = "Stage name to map the domain onto, e.g. $default."
}
