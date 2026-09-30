resource "aws_cloudwatch_event_bus" "this" {
  name = var.bus_name
}

resource "aws_cloudwatch_event_rule" "this" {
  for_each       = var.rules
  name           = each.key
  event_bus_name = aws_cloudwatch_event_bus.this.name
  event_pattern  = each.value.event_pattern
}

resource "aws_cloudwatch_event_target" "this" {
  for_each       = var.rules
  rule           = aws_cloudwatch_event_rule.this[each.key].name
  event_bus_name = aws_cloudwatch_event_bus.this.name
  target_id      = "${each.key}-target"
  arn            = each.value.target_arn
}
