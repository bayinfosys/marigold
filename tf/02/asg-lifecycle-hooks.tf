locals {
  asg_lifecycle_targets = {
    gpu-sm   = aws_autoscaling_group.gpu_sm.name
    gpu-lrg  = aws_autoscaling_group.gpu_lrg.name
    big-cpu  = aws_autoscaling_group.big_cpu.name
    anon-chat = aws_autoscaling_group.anonchat.name
  }

  lifecycle_transitions = ["autoscaling:EC2_INSTANCE_LAUNCHING", "autoscaling:EC2_INSTANCE_TERMINATING"]

  # cartesian product: one hook per asg per transition
  asg_lifecycle_hooks = {
    for pair in setproduct(keys(local.asg_lifecycle_targets), local.lifecycle_transitions) :
    "${pair[0]}-${pair[1] == "autoscaling:EC2_INSTANCE_LAUNCHING" ? "launch" : "terminate"}" => {
      asg_name   = local.asg_lifecycle_targets[pair[0]]
      transition = pair[1]
    }
  }
}

resource "aws_autoscaling_lifecycle_hook" "instance_events" {
  for_each = local.asg_lifecycle_hooks

  name                    = join("-", [var.org_name, var.project_name, var.env, each.key])
  autoscaling_group_name  = each.value.asg_name
  lifecycle_transition    = each.value.transition
  notification_target_arn = aws_sns_topic.asg_hooks.arn
  role_arn                = aws_iam_role.asg_lifecycle_sns.arn
  heartbeat_timeout       = 60
  default_result          = "CONTINUE"
}

resource "aws_iam_role" "asg_lifecycle_sns" {
  name = join("-", [var.org_name, var.project_name, var.env, "asg-lifecycle-sns"])

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "autoscaling.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = var.project_tags
}

resource "aws_iam_role_policy" "asg_lifecycle_sns" {
  name = "sns-publish"
  role = aws_iam_role.asg_lifecycle_sns.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "sns:Publish"
      Resource = aws_sns_topic.asg_hooks.arn
    }]
  })
}

resource "aws_sns_topic" "asg_hooks" {
  name = join("-", [var.org_name, var.project_name, var.env, "asg-hooks"])
  tags = var.project_tags
}

resource "aws_sns_topic_subscription" "asg_hooks_lambda" {
  topic_arn = aws_sns_topic.asg_hooks.arn
  protocol  = "lambda"
  endpoint  = module.asg_lifecycle_lambda.lambda_function_arn
}

resource "aws_lambda_permission" "asg_hooks_sns" {
  statement_id  = "AllowSNSInvoke"
  action        = "lambda:InvokeFunction"
  function_name = module.asg_lifecycle_lambda.lambda_function_name
  principal     = "sns.amazonaws.com"
  source_arn    = aws_sns_topic.asg_hooks.arn
}
