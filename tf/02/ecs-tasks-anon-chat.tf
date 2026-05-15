locals {
  anonchat_model_hash = md5(var.anonchat_model)
  anonchat_env = [
    for k, v in var.models[local.anonchat_model_hash].environment_variables : {
      name  = k
      value = v
    }
  ]
}

resource "aws_ecs_task_definition" "anonchat" {
  family                   = join("-", [var.project_name, var.env, "anonchat"])
  cpu                      = 4096
  memory                   = 14336
  network_mode             = "awsvpc"
  requires_compatibilities = ["EC2"]
  execution_role_arn       = module.ecs.task_exec_iam_role_arn
  task_role_arn            = aws_iam_role.model_task.arn

  container_definitions = jsonencode([{
    name  = "anonchat"
    image = data.aws_ecr_image.environment_image_gpu.image_uri

    resourceRequirements = [{ type = "GPU", value = "1" }]

    command = ["python3", "-c", "from models import sqs_handler; sqs_handler()"]

    environment = concat(
      local.anonchat_env,
      [
        { name = "AWS_DEFAULT_REGION", value = var.region },
        { name = "AWS_SQS_MODEL_QUEUE", value = aws_sqs_queue.anonchat_queue.id },
        { name = "SQS_VISIBILITY_TIMEOUT", value = "120" },
        { name = "DYNAMODB_RESULTS_TABLE", value = aws_dynamodb_table.results_cache.id },
        { name = "DYNAMODB_USAGE_TABLE", value = module.usage_table.dynamodb_table_id },
        { name = "WORKFLOW_STEPS_TABLE", value = aws_dynamodb_table.workflow_steps.id },
        { name = "OUTPUT_BUCKET", value = aws_s3_bucket.model_outputs.id },
        { name = "CACHE_DIR", value = var.efs_model_cache_path },
        { name = "HF_HUB_CACHE", value = var.efs_model_cache_path },
        { name = "HF_HOME", value = "/tmp" },
        { name = "IDLE_TIMEOUT", value = "86400" },
      ]
    )
    mountPoints = [{
      sourceVolume  = "efs-cache"
      containerPath = var.efs_mount_point
      readOnly      = true
    }]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.anonchat.name
        awslogs-region        = var.region
        awslogs-stream-prefix = "anonchat"
      }
    }
  }])

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

  tags = var.project_tags
}

resource "aws_sqs_queue" "anonchat_queue" {
  name                       = join("-", [var.org_name, var.project_name, var.env, "anonchat", "queue"])
  visibility_timeout_seconds = 120
  message_retention_seconds  = 3600

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.anonchat_dlq.arn
    maxReceiveCount     = 3
  })

  tags = var.project_tags
}

resource "aws_sqs_queue" "anonchat_dlq" {
  name                      = join("-", [var.org_name, var.project_name, var.env, "anonchat", "dlq"])
  message_retention_seconds = 86400
}

resource "aws_ecs_service" "anonchat" {
  name            = join("-", [var.project_name, var.env, "anonchat"])
  cluster         = module.ecs.cluster_arn
  task_definition = aws_ecs_task_definition.anonchat.arn
  desired_count   = 2

  capacity_provider_strategy {
    capacity_provider = "anonchat"
    weight            = 100
    base              = 1
  }

  network_configuration {
    subnets         = [for s in data.aws_subnet.private_subnets : s.id]
    security_groups = [aws_security_group.gpu.id]
  }

  force_new_deployment = true

  lifecycle { ignore_changes = [desired_count] }
  tags = var.project_tags
}

resource "aws_cloudwatch_log_group" "anonchat" {
  name              = "/${var.org_name}/${var.project_name}/${var.env}/anonchat"
  retention_in_days = 14
  tags              = var.project_tags
}
