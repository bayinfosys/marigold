locals {
  instance_check_profiles = {
    gpu-sm = {
      image                 = data.aws_ecr_image.environment_image_gpu.image_uri
      expect_gpu            = "1"
      resource_requirements = [{ type = "GPU", value = "1" }]
    }
    gpu-lrg = {
      image                 = data.aws_ecr_image.environment_image_gpu.image_uri
      expect_gpu            = "1"
      resource_requirements = [{ type = "GPU", value = "1" }]
    }
    big-cpu = {
      image                 = data.aws_ecr_image.environment_image.image_uri
      expect_gpu            = "0"
      resource_requirements = []
    }
    test = {
      image                 = data.aws_ecr_image.environment_image.image_uri
      expect_gpu            = "0"
      resource_requirements = []
    }
  }
}

resource "aws_ecs_task_definition" "instance_check" {
  for_each = local.instance_check_profiles

  family                   = join("-", [var.org_name, var.project_name, var.env, "instance-check", each.key])
  cpu                      = 4096
  memory                   = 8192
  network_mode             = "awsvpc"
  requires_compatibilities = ["EC2"]
  execution_role_arn       = module.ecs.task_exec_iam_role_arn
  task_role_arn            = aws_iam_role.model_task.arn

  container_definitions = jsonencode([{
    name  = "instance-check"
    image = each.value.image

    resourceRequirements = each.value.resource_requirements

    command = ["python3", "tools/ecs-task-checker.py"]

    environment = [
      { name = "AWS_DEFAULT_REGION", value = var.region },
      { name = "SMOKE_EXPECT_GPU",       value = each.value.expect_gpu },
      { name = "IMAGE_TAG",              value = var.git_tag },
      { name = "CACHE_DIR",              value = var.efs_model_cache_path },
      { name = "HF_HUB_CACHE",           value = var.efs_model_cache_path },
      { name = "AWS_SQS_MODEL_QUEUE",    value = "instance-check-no-queue" },
      { name = "DYNAMODB_RESULTS_TABLE", value = aws_dynamodb_table.results_cache.id },
      { name = "OUTPUT_BUCKET",          value = aws_s3_bucket.model_outputs.id },
    ]

    mountPoints = [{
      sourceVolume  = "efs-cache"
      containerPath = var.efs_mount_point
      readOnly      = true
    }]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.instance_check.name
        awslogs-region        = var.region
        awslogs-stream-prefix = each.key
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

resource "aws_cloudwatch_log_group" "instance_check" {
  name              = "/${var.org_name}/${var.project_name}/${var.env}/instance-check"
  retention_in_days = 7
  tags              = var.project_tags
}
