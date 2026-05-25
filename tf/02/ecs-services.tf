# ---------------------------------------------------------------------------
# ECS services -- one per model, desired_count managed at runtime by
# task_queuer Lambda. Scale-in handled by CloudWatch CPU alarm.
# ---------------------------------------------------------------------------

resource "aws_ecs_service" "model" {
  for_each = var.models

  name            = join("-", [var.project_name, var.env, each.key, "svc"])
  cluster         = module.ecs.cluster_arn
  task_definition = aws_ecs_task_definition.model[each.key].arn
  desired_count   = 0

  deployment_minimum_healthy_percent = 0
  deployment_maximum_percent         = 100

  # Prevent terraform apply from resetting desired_count to 0
  # while workers are running. Runtime manages this value.
  lifecycle {
    ignore_changes = [desired_count, task_definition]
  }

  capacity_provider_strategy {
    capacity_provider = (
      each.value.gpu_tier == "lrg" ? var.capacity_provider_gpu_lrg :
      each.value.gpu_tier == "sm"  ? var.capacity_provider_gpu_sm  :
      var.capacity_provider_big_cpu
    )
    weight = 1
    base   = 0
  }

  network_configuration {
    subnets          = [for s in data.aws_subnet.private_subnets : s.id]
    security_groups  = [aws_security_group.gpu.id]
    assign_public_ip = false
  }

  tags = var.project_tags
}

# ---------------------------------------------------------------------------
# Application Auto Scaling -- scale-in only, driven by CPU utilisation.
# Scale-out is handled by task_queuer calling update_service directly.
# ---------------------------------------------------------------------------

resource "aws_appautoscaling_target" "model_service" {
  for_each = var.models

  min_capacity       = 0
  max_capacity       = 20
  resource_id        = "service/${module.ecs.cluster_name}/${aws_ecs_service.model[each.key].name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "model_scale_in" {
  for_each = var.models

  name               = join("-", [var.project_name, var.env, each.key, "queue-tracking"])
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.model_service[each.key].resource_id
  scalable_dimension = aws_appautoscaling_target.model_service[each.key].scalable_dimension
  service_namespace  = aws_appautoscaling_target.model_service[each.key].service_namespace

  target_tracking_scaling_policy_configuration {
    target_value       = 10   # messages per worker (matches msg_per_instance)
    scale_in_cooldown  = 60   # seconds -- fast scale-in once queue drains
    scale_out_cooldown = 0    # task_queuer handles scale-out, not this policy

    customized_metric_specification {
      metric_name = "ApproximateNumberOfMessages"
      namespace   = "AWS/SQS"
      statistic   = "Maximum"

      dimensions {
        name  = "QueueName"
        value = aws_sqs_queue.model_queues[each.key].name
      }
    }
  }
}
