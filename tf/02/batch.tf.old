locals {
  name_prefix = join("-", [var.org_name, var.project_name, var.env])
}

#
# alternate deployment of models via aws batch
# this allows us to have:
# + ec2 instances (possibly gpu for separate job queues)
# + single job queues with longer wait times (freemium pricing)
# + no lambda timeouts
# + larger models (image, video, instruct) in same infrastructure
# + spot based pricing
# + memory/cpu provisioning is decoupled (prefer memory)
#
data "aws_iam_policy_document" "assume_ecs_role_policy" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "assume_batch_role_policy" {
  statement {
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["batch.amazonaws.com"]
    }

    actions = ["sts:AssumeRole"]
  }
}

data "aws_iam_policy_document" "assume_ec2_role_policy" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

# Grouping IAM policy attachments using for_each
locals {
  instance_role_policies = [
    "arn:aws:iam::aws:policy/service-role/AmazonEC2ContainerServiceforEC2Role",
    "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
  ]

  execution_role_policies = [
    "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy",
    #    "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly",
    "arn:aws:iam::aws:policy/AmazonElasticFileSystemClientReadWriteAccess"
  ]

  job_role_policies = [
    "arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess"
  ]

  service_role_policy = [
    "arn:aws:iam::aws:policy/service-role/AWSBatchServiceRole"
  ]
}

# roles
resource "aws_iam_role" "instance_role" {
  name               = join("-", [local.name_prefix, "batch_instance_role"])
  assume_role_policy = data.aws_iam_policy_document.assume_ec2_role_policy.json
}

resource "aws_iam_role" "service_role" {
  name               = join("-", [local.name_prefix, "batch_service_role"])
  assume_role_policy = data.aws_iam_policy_document.assume_batch_role_policy.json
}

resource "aws_iam_role" "execution_role" {
  name               = join("-", [local.name_prefix, "batch_execution_role"])
  assume_role_policy = data.aws_iam_policy_document.assume_ecs_role_policy.json
}

resource "aws_iam_role" "job_role" {
  name               = join("-", [local.name_prefix, "batch_job_role"])
  assume_role_policy = data.aws_iam_policy_document.assume_ecs_role_policy.json
}

# role polices
resource "aws_iam_role_policy_attachment" "instance_role_policies" {
  for_each = toset(local.instance_role_policies)

  role       = aws_iam_role.instance_role.name
  policy_arn = each.value
}

resource "aws_iam_role_policy_attachment" "execution_role_policies" {
  for_each = toset(local.execution_role_policies)

  role       = aws_iam_role.execution_role.name
  policy_arn = each.value
}

resource "aws_iam_role_policy_attachment" "job_role_policies" {
  for_each = toset(local.job_role_policies)

  role       = aws_iam_role.job_role.name
  policy_arn = each.value
}

resource "aws_iam_role_policy_attachment" "service_role_policies" {
  for_each = toset(local.service_role_policy)

  role       = aws_iam_role.service_role.name
  policy_arn = each.value
}

# instance profile
resource "aws_iam_instance_profile" "instance_profile" {
  name = join("-", [local.name_prefix, "batch_instance_profile"])
  role = aws_iam_role.instance_role.name
}

resource "aws_placement_group" "sample" {
  name     = join("-", [local.name_prefix, "batch-placement-group"])
  strategy = "cluster"
}

resource "aws_batch_compute_environment" "ec2" {
  compute_environment_name_prefix = join("-", [local.name_prefix, "ec2-simple"])

  service_role = aws_iam_role.service_role.arn
  type         = "MANAGED"

  compute_resources {
    instance_role = aws_iam_instance_profile.instance_profile.arn

    type          = "EC2"
    min_vcpus     = 0
    max_vcpus     = 16
    desired_vcpus = 0
    # https://aws.amazon.com/ec2/pricing/on-demand/
    # https://docs.aws.amazon.com/ec2/latest/instancetypes/instance-type-names.html
    # NB: only certain instance types are allowed, terraform will error if you use the wrong ones
    instance_type = [
      # "m4.large", # 0.116, 8gb, 2cpu
      # "m4.xlarge", # 0.232, 16gb, 4cpu
      # "r5.large", # 0.148, 16gb, 2cpu
      "r5.xlarge", # 0.296, 32gb, 4cpu
      # "t3.xlarge", # 0.188, 16gb, 4cpu
    ]

    # ec2 key for testing - requires public ip in the subnet
    # NB: this creates a cycle somehow, so remove the reference before deleting the resource.
    #ec2_key_pair = aws_key_pair.batch_key.key_name

    security_group_ids = [data.aws_security_group.vpc_default_security_group.id]
    subnets            = [for x in data.aws_subnet.private_subnets : x.id]

    placement_group = aws_placement_group.sample.name

    tags = merge(var.project_tags, {
      Name            = join("-", [local.name_prefix, "batch-instance"])
      EnvironmentName = join("-", [var.org_name, var.project_name, var.env, "ec2-simple"])
    })
  }

  # this role must not be destroyed before the compute-env,
  # if it is the env cannot enumerate the ecs setup and will enter an invalid state
  depends_on = [aws_iam_role.service_role, aws_iam_role_policy_attachment.service_role_policies]

  lifecycle {
    create_before_destroy = true
  }
}

# queue
resource "aws_batch_job_queue" "low_priority_queue" {
  name     = join("-", [local.name_prefix, "low-prio"])
  state    = "ENABLED"
  priority = 1

  compute_environment_order {
    order               = 1
    compute_environment = aws_batch_compute_environment.ec2.arn
  }

  tags = var.project_tags

  #  depends_on = [aws_batch_compute_environment.ec2]
}

resource "aws_cloudwatch_log_group" "batch_instruct" {
  name              = "/aws/batch/batch_instruct"
  retention_in_days = 5

  tags = var.project_tags
}

resource "aws_cloudwatch_log_group" "batch_agent_operation" {
  name              = "/aws/batch/batch_agent_op"
  retention_in_days = 5

  tags = var.project_tags
}


# job definitions
resource "aws_batch_job_definition" "instruct_model_job" {
  name = join("-", [local.name_prefix, "instruct-model-job"])
  type = "container"

  container_properties = jsonencode({
    # command = [model_info.command]
    image            = join(":", [data.aws_ecr_repository.containers["environment"].repository_url, data.aws_ecr_image.images["environment"].image_tag])
    jobRoleArn       = aws_iam_role.job_role.arn
    executionRoleArn = aws_iam_role.execution_role.arn

    # NB: we can put gpu here if we want
    resourceRequirements = [
      { type = "VCPU", value = "2" },
      { type = "MEMORY", value = "8128" }
    ]

    environment = [
      {
        name  = "MODEL_TYPE"
        value = "instruct"
      },
      {
        name  = "CACHE_DIR"
        value = "/mnt/shared/models"
      },
      {
        name  = "HF_HUB_CACHE"
        value = "/mnt/shared/models"
      },
      {
        name  = "PYTHONPATH"
        value = "/usr/local/lib/python3.12:/mnt/shared/packages/lib/python3.12/site-packages"
      }
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.batch_instruct.name
        awslogs-region        = var.region
        awslogs-stream-prefix = "ec2"
      }
    }

    volumes = [
      {
        name = "efs"
        efsVolumeConfiguration = {
          fileSystemId      = data.aws_efs_file_system.efs.id
          rootDirectory     = "/"
          transitEncryption = "ENABLED"
          authorizationConfig = {
            accessPointId = data.aws_efs_access_point.efs_assets_ro.id
            iam           = "ENABLED"
          }
        }
      },
    ]

    mountPoints = [
      {
        containerPath = "/mnt/shared"
        sourceVolume  = "efs"
      },
    ]
  })

  timeout {
    attempt_duration_seconds = 60
  }

  retry_strategy {
    attempts = 1

    evaluate_on_exit {
      action       = "RETRY"
      on_exit_code = "1"
    }

    evaluate_on_exit {
      action       = "EXIT"
      on_exit_code = "0"
    }
  }

  tags = var.project_tags
}


#
# open access for testing
#
#resource "tls_private_key" "batch_key" {
#  algorithm = "RSA"
#  rsa_bits  = 4096
#}
#
#resource "aws_key_pair" "batch_key" {
#  key_name   = "ec2-batch-key"
#  public_key = tls_private_key.batch_key.public_key_openssh
#}

#resource "local_file" "batch_key_pem" {
#  content  = tls_private_key.batch_key.private_key_pem
#  filename = "${path.module}/ec2-batch-instance.pem"
#  file_permission = "0600"
#}
#
#resource "aws_security_group_rule" "allow_ssh" {
#  type        = "ingress"
#  from_port   = 22
#  to_port     = 22
#  protocol    = "tcp"
#  cidr_blocks = ["82.5.170.78/32"]  # Restrict SSH access to your IP
#  security_group_id = data.aws_security_group.vpc_default_security_group.id
#}
