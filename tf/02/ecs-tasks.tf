# ---------------------------------------------------------------------------
# ECS task definitions -- one per model declared in models.yaml.
#
# Each task:
#   - runs the environment container image
#   - mounts the EFS model cache read-only at /mnt/shared
#   - reads its work queue URL from the environment
#   - runs on FARGATE or FARGATE_SPOT by default
#
# To route a specific model to GPU, add a capacity_provider_strategy block
# to its task definition and ensure the GPU ASG has available capacity.
# ---------------------------------------------------------------------------

resource "aws_ecs_task_definition" "model_tasks" {
  for_each = var.models

  # Family name must match [a-zA-Z0-9_-] and be <= 255 characters.
  family = join("-", [var.project_name, var.env, each.key])

  cpu                      = "4096"
  memory                   = tostring(each.value.memory_size)
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  execution_role_arn       = module.ecs.task_exec_iam_role_arn
  task_role_arn            = aws_iam_role.model_task.arn

  container_definitions = jsonencode([
    {
      name  = "infer"
      image = data.aws_ecr_image.environment_image.image_uri
      cpu   = 4096
      memory = each.value.memory_size

      command = [
        "python", "-c",
        "from ${each.value.handler} import sqs_handler; sqs_handler()"
      ]

      environment = concat(
        [
          for k, v in each.value.environment_variables : {
            name  = k
            value = v
          }
        ],
        [
          { name = "AWS_SQS_MODEL_QUEUE",        value = aws_sqs_queue.model_queues[each.key].id },
          { name = "RESULTS_TABLE",              value = aws_dynamodb_table.results_cache.id },
          { name = "DYNAMODB_USAGE_TABLE",        value = module.usage_table.dynamodb_table_id },
          { name = "CACHE_DIR",                  value = "/mnt/shared/models" },
          { name = "HF_HUB_CACHE",               value = "/mnt/shared/models" },
          { name = "HF_HUB_DISABLE_PROGRESS_BARS", value = "1" },
          { name = "HF_HUB_DISABLE_TELEMETRY",   value = "1" },
          { name = "HF_HOME",                    value = "/tmp" },
          { name = "HF_HUB_OFFLINE",             value = "1" },
          { name = "REMOTE_CODE",                value = "0" },
          { name = "USE_FAST",                   value = "0" },
          { name = "OUTPUT_BUCKET",              value = aws_s3_bucket.model_outputs.id },
        ]
      )

      mountPoints = [
        {
          sourceVolume  = "efs-cache"
          containerPath = "/mnt/shared"
          readOnly      = true
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.ecs_model_logs[each.key].name
          awslogs-region        = var.region
          awslogs-stream-prefix = each.key
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

  volume {
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
