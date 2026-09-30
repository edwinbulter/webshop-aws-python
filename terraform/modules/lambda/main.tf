locals {
  build_dir = "${var.repo_root}/.terraform-build/${var.function_name}"

  source_files = flatten([
    for p in var.source_paths : [
      for f in fileset("${var.repo_root}/${p}", "**") : "${var.repo_root}/${p}/${f}"
    ]
  ])
  source_hash = sha1(join("", [for f in local.source_files : filesha1(f)]))
}

resource "null_resource" "build" {
  triggers = {
    source_hash = local.source_hash
    lock_hash   = var.install_dependencies ? "${filemd5("${var.repo_root}/pyproject.toml")}-${filemd5("${var.repo_root}/uv.lock")}" : "none"
  }

  provisioner "local-exec" {
    command = "bash ${path.module}/scripts/build.sh ${local.build_dir} ${var.repo_root} ${var.install_dependencies} ${join(" ", var.source_paths)}"
  }
}

data "archive_file" "package" {
  type        = "zip"
  source_dir  = local.build_dir
  output_path = "${local.build_dir}.zip"
  depends_on  = [null_resource.build]
}

resource "aws_cloudwatch_log_group" "this" {
  name              = "/aws/lambda/${var.function_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_iam_role" "this" {
  name = "${var.function_name}-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "logs" {
  name = "${var.function_name}-logs"
  role = aws_iam_role.this.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
      Resource = ["${aws_cloudwatch_log_group.this.arn}:*"]
    }]
  })
}

resource "aws_iam_role_policy" "extra" {
  count = length(var.iam_policy_statements) > 0 ? 1 : 0
  name  = "${var.function_name}-extra"
  role  = aws_iam_role.this.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      for s in var.iam_policy_statements : {
        Effect   = "Allow"
        Action   = s.actions
        Resource = s.resources
      }
    ]
  })
}

resource "aws_iam_role_policy" "sqs_poll" {
  count = var.has_sqs_trigger ? 1 : 0
  name  = "${var.function_name}-sqs-poll"
  role  = aws_iam_role.this.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
      Resource = [var.sqs_trigger_queue_arn]
    }]
  })
}

resource "aws_lambda_function" "this" {
  function_name    = var.function_name
  role             = aws_iam_role.this.arn
  handler          = var.handler
  runtime          = var.runtime
  timeout          = var.timeout
  memory_size      = var.memory_size
  filename         = data.archive_file.package.output_path
  source_code_hash = data.archive_file.package.output_base64sha256

  environment {
    variables = var.environment_variables
  }

  depends_on = [aws_cloudwatch_log_group.this, aws_iam_role_policy.logs]
}

resource "aws_lambda_event_source_mapping" "sqs" {
  count                   = var.has_sqs_trigger ? 1 : 0
  event_source_arn        = var.sqs_trigger_queue_arn
  function_name           = aws_lambda_function.this.arn
  batch_size              = var.sqs_batch_size
  function_response_types = ["ReportBatchItemFailures"]
}
