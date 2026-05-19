

module "asg_lifecycle_lambda" {
  source = "terraform-aws-modules/lambda/aws"

  function_name                     = join("-", [var.org_name, var.project_name, var.env, "asg-lifecycle"])
  description                       = "Receives asg lifecycle hooks to monitor instance start and termination"
  hash_extra                        = "asg-lifecycle"
  cloudwatch_logs_retention_in_days = 5
  runtime                           = var.lambda_runtime

  reserved_concurrent_executions = 1

  source_path = [{
    path             = join("/", [path.module, "..", "..", "package", "src"]),
    pip_requirements = join("/", [path.module, "..", "..", "requirements.polling.txt"])
  }]

  handler = "tools.state_machine.asg_lifecycle.handler"

  environment_variables = {
    LIFECYCLE_TOPIC_ARN = aws_sns_topic.lifecycle.arn
    BUILD_VERSION       = var.git_tag
  }

  policy_statements = {
    ec2_describe = {
      effect    = "Allow"
      actions   = ["ec2:DescribeInstances"]
      resources = ["*"]
    }

    autoscaling_complete = {
      effect    = "Allow"
      actions   = ["autoscaling:CompleteLifecycleAction"]
      resources = ["*"]
    }

    sns_publish = {
      effect    = "Allow"
      actions   = ["sns:Publish"]
      resources = [aws_sns_topic.lifecycle.arn]
    }
  }

  attach_policy_statements = true
  tags                     = var.project_tags
}
