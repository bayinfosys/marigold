# ---------------------------------------------------------------------------
# ECS task definitions -- one per model declared in models.yaml.
#
# Split into three resources by compute tier:
#
#   aws_ecs_task_definition.cpu      -- CPU-only image, gpu_tier=none
#   aws_ecs_task_definition.gpu_sm   -- EC2 gpu-sm capacity provider, T4
#   aws_ecs_task_definition.gpu_lrg  -- EC2 gpu-lrg capacity provider, A10G
#
# gpu_tier in models.yaml drives the split:
#   none  -> cpu
#   sm    -> gpu_sm
#   lrg   -> gpu_lrg
# ---------------------------------------------------------------------------

locals {
  cpu_models     = { for k, v in var.models : k => v if v.gpu_tier == "none" }
  gpu_sm_models  = { for k, v in var.models : k => v if v.gpu_tier == "sm"   }
  gpu_lrg_models = { for k, v in var.models : k => v if v.gpu_tier == "lrg"  }
  gpu_models     = merge(local.gpu_sm_models, local.gpu_lrg_models)
}

# ---------------------------------------------------------------------------
# Shared environment builder function (local helper)
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
      { name = "SQS_POLL_WAIT_TIME",     value = "45" },
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
}

# ---------------------------------------------------------------------------
# CPU task definitions (Fargate, gpu_tier=none)
# ---------------------------------------------------------------------------

resource "aws_ecs_task_definition" "cpu" {
  for_each = local.cpu_models

  family                   = join("-", [var.project_name, var.env, each.key, "cpu"])
  network_mode             = "awsvpc"
  requires_compatibilities = ["EC2"]
  execution_role_arn       = module.ecs.task_exec_iam_role_arn
  task_role_arn            = aws_iam_role.model_task.arn

  container_definitions = jsonencode([{
    name   = each.key
    image  = data.aws_ecr_image.environment_image.image_uri
    memory = each.value.memory_res

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

# ---------------------------------------------------------------------------
# GPU sm task definitions (EC2, gpu_tier=sm, T4 16GB)
# ---------------------------------------------------------------------------

resource "aws_ecs_task_definition" "gpu_sm" {
  for_each = local.gpu_sm_models

  family                   = join("-", [var.project_name, var.env, each.key, "gpu"])
  network_mode             = "awsvpc"
  requires_compatibilities = ["EC2"]
  execution_role_arn       = module.ecs.task_exec_iam_role_arn
  task_role_arn            = aws_iam_role.model_task.arn

  container_definitions = jsonencode([{
    name   = each.key
    image  = data.aws_ecr_image.environment_image_gpu.image_uri
    memoryReservation = each.value.memory_res

    resourceRequirements = each.value.gpu_units > 0 ? [{
      type  = "GPU"
      value = tostring(each.value.gpu_units)
    }] : []

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

# ---------------------------------------------------------------------------
# GPU lrg task definitions (EC2, gpu_tier=lrg, A10G 24GB+)
# ---------------------------------------------------------------------------

resource "aws_ecs_task_definition" "gpu_lrg" {
  for_each = local.gpu_lrg_models

  family                   = join("-", [var.project_name, var.env, each.key, "gpu"])
  network_mode             = "awsvpc"
  requires_compatibilities = ["EC2"]
  execution_role_arn       = module.ecs.task_exec_iam_role_arn
  task_role_arn            = aws_iam_role.model_task.arn

  container_definitions = jsonencode([{
    name   = each.key
    image  = data.aws_ecr_image.environment_image_gpu.image_uri
    memoryReservation = each.value.memory_res

    resourceRequirements = each.value.gpu_units > 0 ? [{
      type  = "GPU"
      value = tostring(each.value.gpu_units)
    }] : []

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

# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------

output "efs_mount_point" {
  description = "location to mount the efs disk for correct path access"
  value       = var.efs_mount_point
}

output "efs_model_cache_path" {
  description = "Container-relative path where HuggingFace model weights are cached on EFS."
  value       = var.efs_model_cache_path
}
