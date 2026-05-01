# ---------------------------------------------------------------------------
# ECS services -- one per model declared in models.yaml.
#
# CPU services (Fargate):
#   Start at desired_count=0. Application Auto Scaling drives them up when
#   the SQS queue is non-empty and back to 0 when the queue drains.
#
# GPU services (EC2):
#   Placeholder services at desired_count=0. Will not schedule work until
#   the GPU capacity provider has active EC2 instances. launch_type is
#   temporarily set to FARGATE so the resource can be created. Switch to
#   capacity_provider_strategy when GPU instances are available.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Local: idle period calculation
#
# idle_timeout is in seconds. CloudWatch alarm evaluation_periods counts
# 60-second periods. Convert and floor to a minimum of 1.
# A model with idle_timeout=3600 keeps its task running for 60 periods
# (1 hour) after its queue empties before scaling to zero.
# ---------------------------------------------------------------------------

locals {
  idle_periods = {
    for k, v in var.models : k => max(1, floor(v.idle_timeout / 60))
    if !v.requires_gpu
  }
}

# ---------------------------------------------------------------------------
# CPU services (Fargate)
# ---------------------------------------------------------------------------

resource "aws_ecs_service" "model_services_cpu" {
  for_each = {
    for k, v in var.models : k => v if !v.requires_gpu
  }

  name            = join("-", [var.project_name, var.env, each.key])
  cluster         = module.ecs.cluster_arn
  task_definition = aws_ecs_task_definition.model_tasks[each.key].arn
  desired_count   = 0
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = [for s in data.aws_subnet.private_subnets : s.id]
    security_groups  = [data.aws_security_group.vpc_default_security_group.id]
    assign_public_ip = false
  }

  lifecycle {
    ignore_changes = [desired_count]
  }

  tags = var.project_tags
}

# ---------------------------------------------------------------------------
# GPU services (EC2 placeholder)
# ---------------------------------------------------------------------------

resource "aws_ecs_service" "model_services_gpu" {
  for_each = var.enable_gpu_services ? {
    for k, v in var.models : k => v if v.requires_gpu
  } : {}

  name            = join("-", [var.project_name, var.env, each.key])
  cluster         = module.ecs.cluster_arn
  task_definition = aws_ecs_task_definition.model_tasks[each.key].arn
  desired_count   = 0

  capacity_provider_strategy {
    capacity_provider = "gpu"
    weight            = 100
    base              = 0
  }

  network_configuration {
    subnets          = [for s in data.aws_subnet.private_subnets : s.id]
    security_groups  = [data.aws_security_group.vpc_default_security_group.id]
    assign_public_ip = false
  }

  lifecycle {
    ignore_changes = [desired_count, task_definition]
  }

  tags = var.project_tags
}

# ---------------------------------------------------------------------------
# Application Auto Scaling -- CPU services only
# ---------------------------------------------------------------------------

resource "aws_appautoscaling_target" "model_services_cpu" {
  for_each = {
    for k, v in var.models : k => v if !v.requires_gpu
  }

  max_capacity       = 1
  min_capacity       = 0
  resource_id        = "service/${module.ecs.cluster_name}/${aws_ecs_service.model_services_cpu[each.key].name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"

  depends_on = [aws_ecs_service.model_services_cpu]
}

resource "aws_appautoscaling_policy" "scale_up" {
  for_each = {
    for k, v in var.models : k => v if !v.requires_gpu
  }

  name               = join("-", [var.project_name, var.env, each.key, "scale-up"])
  policy_type        = "StepScaling"
  resource_id        = aws_appautoscaling_target.model_services_cpu[each.key].resource_id
  scalable_dimension = aws_appautoscaling_target.model_services_cpu[each.key].scalable_dimension
  service_namespace  = aws_appautoscaling_target.model_services_cpu[each.key].service_namespace

  step_scaling_policy_configuration {
    adjustment_type         = "ExactCapacity"
    cooldown                = 60
    metric_aggregation_type = "Maximum"

    step_adjustment {
      metric_interval_lower_bound = 0
      scaling_adjustment          = 1
    }
  }
}

resource "aws_appautoscaling_policy" "scale_down" {
  for_each = {
    for k, v in var.models : k => v if !v.requires_gpu
  }

  name               = join("-", [var.project_name, var.env, each.key, "scale-down"])
  policy_type        = "StepScaling"
  resource_id        = aws_appautoscaling_target.model_services_cpu[each.key].resource_id
  scalable_dimension = aws_appautoscaling_target.model_services_cpu[each.key].scalable_dimension
  service_namespace  = aws_appautoscaling_target.model_services_cpu[each.key].service_namespace

  step_scaling_policy_configuration {
    adjustment_type         = "ExactCapacity"
    cooldown                = 60
    metric_aggregation_type = "Maximum"

    step_adjustment {
      metric_interval_upper_bound = 0
      scaling_adjustment          = 0
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "queue_not_empty" {
  for_each = {
    for k, v in var.models : k => v if !v.requires_gpu
  }

  alarm_name          = join("-", [var.project_name, var.env, each.key, "queue-not-empty"])
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Maximum"
  threshold           = 0
  treat_missing_data  = "notBreaching"

  dimensions = {
    QueueName = aws_sqs_queue.model_queues[each.key].name
  }

  alarm_actions = [aws_appautoscaling_policy.scale_up[each.key].arn]

  tags = var.project_tags
}

resource "aws_cloudwatch_metric_alarm" "queue_empty" {
  for_each = {
    for k, v in var.models : k => v if !v.requires_gpu
  }

  alarm_name          = join("-", [var.project_name, var.env, each.key, "queue-empty"])
  comparison_operator = "LessThanOrEqualToThreshold"
  evaluation_periods  = local.idle_periods[each.key]
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Maximum"
  threshold           = 0
  treat_missing_data  = "notBreaching"

  dimensions = {
    QueueName = aws_sqs_queue.model_queues[each.key].name
  }

  alarm_actions = [aws_appautoscaling_policy.scale_down[each.key].arn]

  tags = var.project_tags
}
