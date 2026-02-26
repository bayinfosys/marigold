locals {
  assets_bucket_arn = data.terraform_remote_state.pipelines.outputs["asset_bucket_arn"]
}

data "aws_iam_policy_document" "cache_builder_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "cache_builder" {
  name               = join("-", [var.org_name, var.project_name, var.env, "cache-builder"])
  assume_role_policy = data.aws_iam_policy_document.cache_builder_assume.json
  tags               = var.project_tags
}

data "aws_iam_policy_document" "cache_builder" {
  # EFS: mount and write via the rw access point.
  # Scoped to the access point ARN, not the file system, so the role cannot
  # mount the file system outside of the access point's path and POSIX context.
  statement {
    sid    = "EFSWrite"
    effect = "Allow"
    actions = [
      "elasticfilesystem:ClientMount",
      "elasticfilesystem:ClientWrite",
      "elasticfilesystem:ClientRootAccess",
    ]
    resources = [
      data.terraform_remote_state.containers.outputs["efs_assets_rw_arn"],
    ]
  }

  # S3: read scripts and models.json from the assets bucket
  statement {
    sid       = "S3Read"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${local.assets_bucket_arn}/*"]
  }

  # SSM: read the HuggingFace token parameter
  statement {
    sid       = "SSMGetToken"
    effect    = "Allow"
    actions   = ["ssm:GetParameter"]
    resources = [aws_ssm_parameter.hf_token.arn]
  }

  # EC2: self-terminate only
  # The instance terminates itself once the cache run is complete.
  statement {
    sid       = "EC2SelfTerminate"
    effect    = "Allow"
    actions   = ["ec2:TerminateInstances"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "ec2:ResourceTag/Name"
      values   = [join("-", [var.org_name, var.project_name, var.env, "cache-builder"])]
    }
  }

  # CloudWatch Logs: write instance logs
  statement {
    sid    = "CloudWatchLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "cache_builder" {
  name   = join("-", [var.org_name, var.project_name, var.env, "cache-builder-policy"])
  role   = aws_iam_role.cache_builder.id
  policy = data.aws_iam_policy_document.cache_builder.json
}

# SSM Session Manager access (replaces SSH)
resource "aws_iam_role_policy_attachment" "ssm_managed" {
  role       = aws_iam_role.cache_builder.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "cache_builder" {
  name = join("-", [var.org_name, var.project_name, var.env, "cache-builder"])
  role = aws_iam_role.cache_builder.name
}
