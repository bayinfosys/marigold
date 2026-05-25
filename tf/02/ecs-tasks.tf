# ---------------------------------------------------------------------------
# ECS task definitions -- one per model, tier-parameterised.
# ---------------------------------------------------------------------------

# Builds the environment list for a container definition.
# Used identically by all three task definition resources.
locals {
  def_env = { for k, v in var.models : k => concat(
    [for ek, ev in v.environment_variables : { name = ek, value = ev }],
    [
      { name = "AWS_DEFAULT_REGION",     value = var.region },
      { name = "AWS_SQS_MODEL_QUEUE",    value = aws_sqs_queue.model_queues[k].id },
      { name = "DYNAMODB_RESULTS_TABLE", value = aws_dynamodb_table.results_cache.id },
      { name = "DYNAMODB_USAGE_TABLE",   value = module.usage_table.dynamodb_table_id },
      { name = "WORKFLOW_STEPS_TABLE",   value = aws_dynamodb_table.workflow_steps.id },
      { name = "OUTPUT_BUCKET",          value = aws_s3_bucket.model_outputs.id },
      { name = "SQS_VISIBILITY_TIMEOUT", value = tostring(v.timeout) },
      { name = "LIFECYCLE_TOPIC_ARN",    value = aws_sns_topic.lifecycle.arn },
      { name = "MODEL_HASH",             value = k },
      { name = "MODEL_NAME",             value = v.environment_variables["MODELNAME"] },
    ],
    v.provider == "huggingface" ? [
      { name = "CACHE_DIR",                    value = var.efs_model_cache_path },
      { name = "HF_HUB_CACHE",                 value = var.efs_model_cache_path },
      { name = "HF_HOME",                      value = "/tmp" },
      { name = "HF_HUB_OFFLINE",               value = "1" },
      { name = "HF_HUB_DISABLE_PROGRESS_BARS", value = "1" },
      { name = "HF_HUB_DISABLE_TELEMETRY",     value = "1" },
      { name = "REMOTE_CODE",                  value = "0" },
      { name = "USE_FAST",                     value = "0" },
    ] : [],
    v.auth_required ? [
      { name = "HF_TOKEN", value = var.hf_token }
    ] : []
  )}

  # Tier configuration -- all tier-specific values in one place.
  task_tiers = {
    none = {
      image             = data.aws_ecr_image.environment_image.image_uri
      memory_mode       = "hard"   # cpu uses memory, gpu uses memoryReservation
      gpu_required      = false
      family_suffix     = "cpu"
    }
    sm = {
      image             = data.aws_ecr_image.environment_image_gpu.image_uri
      memory_mode       = "soft"
      gpu_required      = true
      family_suffix     = "gpu"
    }
    lrg = {
      image             = data.aws_ecr_image.environment_image_gpu.image_uri
      memory_mode       = "soft"
      gpu_required      = true
      family_suffix     = "gpu"
    }
  }
}

resource "aws_ecs_task_definition" "model" {
  for_each = var.models

  family                   = join("-", [var.project_name, var.env, each.key, local.task_tiers[each.value.gpu_tier].family_suffix])
  network_mode             = "awsvpc"
  requires_compatibilities = ["EC2"]
  execution_role_arn       = module.ecs.task_exec_iam_role_arn
  task_role_arn            = aws_iam_role.model_task.arn

  container_definitions = jsonencode([{
    name  = each.key
    image = local.task_tiers[each.value.gpu_tier].image

    # Hard memory limit for CPU tasks, soft reservation for GPU tasks
    # (GPU tasks share host memory more flexibly).
    memory            = local.task_tiers[each.value.gpu_tier].memory_mode == "hard" ? each.value.memory_res : null
    memoryReservation = local.task_tiers[each.value.gpu_tier].memory_mode == "soft" ? each.value.memory_res : null

    resourceRequirements = (
      local.task_tiers[each.value.gpu_tier].gpu_required && each.value.gpu_units > 0
    ) ? [{ type = "GPU", value = tostring(each.value.gpu_units) }] : []

    command = ["python3", "-c", "from models import sqs_handler; sqs_handler()"]

    environment = local.def_env[each.key]

    mountPoints = each.value.provider == "huggingface" ? [{
      sourceVolume  = "efs-cache"
      containerPath = var.efs_mount_point
      readOnly      = true
    }] : []

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.ecs_model_logs[each.key].name
        awslogs-region        = var.region
        awslogs-stream-prefix = each.value.environment_variables["MODELNAME"]
      }
    }

    healthCheck = {
      command     = ["CMD-SHELL", "python3 -c 'exit(0)'"]
      interval    = 30
      retries     = 3
      startPeriod = 20
      timeout     = 5
    }
  }])

  dynamic "volume" {
    for_each = each.value.provider == "huggingface" ? [1] : []
    content {
      name = "efs-cache"
      efs_volume_configuration {
        file_system_id     = data.aws_efs_file_system.efs.id
        root_directory     = "/"
        transit_encryption = "ENABLED"
        authorization_config {
          access_point_id = data.aws_efs_access_point.efs_assets_ro.id
          iam             = "ENABLED"
        }
      }
    }
  }

  tags = var.project_tags
}
