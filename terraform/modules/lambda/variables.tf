variable "function_name" {
  type        = string
  description = "Name of the Lambda function."
}

variable "handler" {
  type        = string
  description = "Python import path to the handler, e.g. app.main.handler."
}

variable "runtime" {
  type    = string
  default = "python3.13"
}

variable "timeout" {
  type    = number
  default = 10
}

variable "memory_size" {
  type    = number
  default = 256
}

variable "repo_root" {
  type        = string
  description = "Absolute path to the repository root, used to resolve source_paths and requirements_file."
}

variable "source_paths" {
  type        = list(string)
  description = "Directories (relative to repo_root) to bundle into the deployment package, e.g. [\"app\"]."
}

variable "requirements_file" {
  type        = string
  default     = null
  description = "Path (relative to repo_root) to a requirements.txt to pip install into the package. Null skips this (used by consumers, which only need boto3 -- already provided by the Lambda runtime)."
}

variable "environment_variables" {
  type    = map(string)
  default = {}
}

variable "log_retention_days" {
  type    = number
  default = 14
}

variable "iam_policy_statements" {
  type = list(object({
    actions   = list(string)
    resources = list(string)
  }))
  default     = []
  description = "Extra least-privilege IAM statements for this function's execution role, beyond basic CloudWatch Logs access."
}

variable "sqs_trigger_queue_arn" {
  type        = string
  default     = null
  description = "If set, wires this function to the given SQS queue via a native event source mapping (not via EventBridge invoking Lambda directly)."
}

variable "sqs_batch_size" {
  type    = number
  default = 10
}
