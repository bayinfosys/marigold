# ---------------------------------------------------------------------------
# ECS services -- one per model declared in models.yaml.
#
# CPU services (Fargate, gpu_tier=none):
#   Start at desired_count=0. Application Auto Scaling drives them up when
#   the SQS queue is non-empty and back to 0 when the queue drains.
#
# GPU sm services (EC2, gpu_tier=sm, T4):
#   Desired count managed by the polling Lambda via RunTask.
#   Capacity provider routes to gpu-sm ASG (g4dn family).
#
# GPU lrg services (EC2, gpu_tier=lrg, A10G):
#   Desired count managed by the polling Lambda via RunTask.
#   Capacity provider routes to gpu-lrg ASG (g5 family).
# ---------------------------------------------------------------------------

locals {
  cpu_service_models     = { for k, v in var.models : k => v if v.gpu_tier == "none" }
  gpu_sm_service_models  = { for k, v in var.models : k => v if v.gpu_tier == "sm"   }
  gpu_lrg_service_models = { for k, v in var.models : k => v if v.gpu_tier == "lrg"  }

  # idle_timeout in seconds -> CloudWatch evaluation periods (60s each), min 1
  idle_periods = {
    for k, v in var.models : k => max(1, floor(v.idle_timeout / 60))
    if v.gpu_tier == "none"
  }
}

# ---------------------------------------------------------------------------
# CPU services (EC2, gpu_tier=none)
# ---------------------------------------------------------------------------

resource "aws_ecs_service" "model_services_cpu" {
  for_each = local.cpu_service_models

  name            = join("-", [var.project_name, var.env, each.key])
  cluster         = module.ecs.cluster_arn
  task_definition = aws_ecs_task_definition.cpu[each.key].arn
  desired_count   = 0

  capacity_provider_strategy {
    capacity_provider = var.capacity_provider_big_cpu
    weight            = 1
    base              = 0
  }

  force_new_deployment = true

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
# GPU sm services (EC2, gpu_tier=sm, g4dn/T4)
# ---------------------------------------------------------------------------

resource "aws_ecs_service" "model_services_gpu_sm" {
  for_each = local.gpu_sm_service_models

  name            = join("-", [var.project_name, var.env, each.key])
  cluster         = module.ecs.cluster_arn
  task_definition = aws_ecs_task_definition.gpu_sm[each.key].arn
  desired_count   = 0

  capacity_provider_strategy {
    capacity_provider = var.capacity_provider_gpu_sm
    weight            = 1
    base              = 0
  }

  force_new_deployment = true

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
# GPU lrg services (EC2, gpu_tier=lrg, g5/A10G)
# ---------------------------------------------------------------------------

resource "aws_ecs_service" "model_services_gpu_lrg" {
  for_each = local.gpu_lrg_service_models

  name            = join("-", [var.project_name, var.env, each.key])
  cluster         = module.ecs.cluster_arn
  task_definition = aws_ecs_task_definition.gpu_lrg[each.key].arn
  desired_count   = 0

  capacity_provider_strategy {
    capacity_provider = var.capacity_provider_gpu_lrg
    weight            = 1
    base              = 0
  }

  force_new_deployment = true

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
#
# GPU services are launched on demand by the polling Lambda via RunTask.
# Auto scaling for GPU would require custom metrics and is deferred.
# ---------------------------------------------------------------------------

resource "aws_appautoscaling_target" "model_services_cpu" {
  for_each = local.cpu_service_models

  max_capacity       = 1
  min_capacity       = 0
  resource_id        = "service/${module.ecs.cluster_name}/${aws_ecs_service.model_services_cpu[each.key].name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"

  tags = var.project_tags

  depends_on = [aws_ecs_service.model_services_cpu]
}

resource "aws_appautoscaling_policy" "scale_up" {
  for_each = local.cpu_service_models

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
  for_each = local.cpu_service_models

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
  for_each = local.cpu_service_models

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
  for_each = local.cpu_service_models

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
