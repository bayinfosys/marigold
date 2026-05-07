# ---------------------------------------------------------------------------
# ECS task definitions -- one per model declared in models.yaml.
#
# Each task:
#   - runs the shared environment container image (single image for all models)
#   - mounts the EFS model cache read-only at /mnt/shared
#   - reads its work queue URL from the environment
#   - runs on FARGATE by default
#
# To route a specific model to GPU, add a capacity_provider_strategy block
# to its task definition and ensure the GPU ASG has available capacity.
# ---------------------------------------------------------------------------

resource "aws_ecs_task_definition" "model_tasks" {
  for_each = var.models

  # Family name must match [a-zA-Z0-9_-] and be <= 255 characters.
  family                   = join("-", [var.project_name, var.env, each.key])
  cpu                      = each.value.cpu_size
  memory                   = each.value.memory_size
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  execution_role_arn       = module.ecs.task_exec_iam_role_arn
  task_role_arn            = aws_iam_role.model_task.arn

  container_definitions = jsonencode([
    {
      # TODO: how can we change:
      # + the container (if we need cuda)
      # + the cpu inline with the memory
      # + the name to be model based
      name   = each.key
      image  = data.aws_ecr_image.environment_image.image_uri
      cpu    = each.value.cpu_size
      memory = each.value.memory_size
      # requires_compatibilities = each.value.requires_gpu ? ["EC2"] : ["FARGATE"]
      # resourceRequirements = each.value.requires_gpu ? [
      #   { type = "GPU", value = "1" }
      # ] : []

      command = [
        "python", "-c",
        "from models import sqs_handler; sqs_handler()"
      ]

      environment = concat(
        # model-specific variables from models.yaml (MODELNAME, MODEL_TYPE, etc.)
        [
          for k, v in each.value.environment_variables : { name = k, value = v }
        ],
        # infrastructure variables injected by Terraform
        [
          { name = "AWS_SQS_MODEL_QUEUE",  value = aws_sqs_queue.model_queues[each.key].id },
          { name = "DYNAMODB_RESULTS_TABLE", value = aws_dynamodb_table.results_cache.id },
          { name = "DYNAMODB_USAGE_TABLE", value = module.usage_table.dynamodb_table_id },
          { name = "WORKFLOW_STEPS_TABLE", value = aws_dynamodb_table.workflow_steps.id },
          { name = "OUTPUT_BUCKET",        value = aws_s3_bucket.model_outputs.id },
          { name = "SQS_VISIBILITY_TIMEOUT", value = tostring(each.value.timeout) },
          { name = "IDLE_TIMEOUT",         value = tostring(each.value.idle_timeout) },
        ],
        # HF_TOKEN is only injected for gated models
        # NB: if  provider is not huggingface, we need a different thing
        each.value.provider == "huggingface" ? [
          { name = "CACHE_DIR",                    value = var.efs_model_cache_path },
          { name = "HF_HUB_CACHE",                 value = var.efs_model_cache_path },
          { name = "HF_HOME",                      value = "/tmp" },
          { name = "HF_HUB_OFFLINE",               value = "1" },
          { name = "HF_HUB_DISABLE_PROGRESS_BARS", value = "1" },
          { name = "HF_HUB_DISABLE_TELEMETRY",     value = "1" },
          { name = "REMOTE_CODE",                  value = "0" },
          { name = "USE_FAST",                     value = "0" },
        ] : [],
        each.value.auth_required ? [
          { name = "HF_TOKEN", value = var.hf_token }
        ] : []
      )

      mountPoints = each.value.provider == "huggingface" ? [
        {
          sourceVolume  = "efs-cache"
          containerPath = var.efs_mount_point
          readOnly      = true
        }
      ] : []

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.ecs_model_logs[each.key].name
          awslogs-region        = var.region
          awslogs-stream-prefix = each.value.environment_variables["MODELNAME"]
        }
      }

      healthCheck = {
        command     = ["CMD-SHELL", "python -c 'exit(0)'"]
        interval    = 30
        retries     = 3
        startPeriod = 20
        timeout     = 5
      }
    }
  ])

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
}

output "efs_mount_point" {
  description = "location to mount the efs disk for correct path access"
  value       = var.efs_mount_point
}

output "efs_model_cache_path" {
  description = "Container-relative path where HuggingFace model weights are cached on EFS."
  value       = var.efs_model_cache_path
}
