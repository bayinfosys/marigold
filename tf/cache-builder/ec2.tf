#
# Locals: references into remote state
#
locals {
  vpc_id              = data.terraform_remote_state.containers.outputs["vpc_id"]
  public_subnet_id    = data.terraform_remote_state.containers.outputs["vpc_public_subnet_ids"][0]
  efs_file_system_id  = data.terraform_remote_state.containers.outputs["efs_file_system_id"]
  efs_access_point_id = data.terraform_remote_state.containers.outputs["efs_assets_rw_id"]
  assets_bucket       = data.terraform_remote_state.pipelines.outputs["asset_bucket_name"]
  models_json_key     = data.terraform_remote_state.pipelines.outputs["models_json_s3_key"]
  models_json_etag    = data.terraform_remote_state.pipelines.outputs["models_json_s3_etag"]
  cache_models_key    = data.terraform_remote_state.pipelines.outputs["cache_models_script_s3_key"]
  cache_model_key     = data.terraform_remote_state.pipelines.outputs["cache_model_script_s3_key"]
}

#
# AMI: Amazon Linux 2023
#
data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-x86_64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

#
# Security group: outbound only.
# SSM Session Manager handles console access -- no inbound ports required.
#
resource "aws_security_group" "cache_builder" {
  name        = join("-", [var.org_name, var.project_name, var.env, "cache-builder"])
  description = "Cache builder EC2: outbound only, access via SSM Session Manager"
  vpc_id      = local.vpc_id

  egress {
    description = "allow all outbound (HuggingFace downloads, SSM, EFS, S3)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = var.project_tags
}

#
# EC2 instance.
#
# Placement: public subnet with a public IP. This gives direct internet access
# for HuggingFace downloads without requiring a NAT gateway.
#
# Replacement trigger: when models.json changes in S3 (i.e. after make apply/02
# following a change to assets/models.yaml), re-applying this layer replaces
# the instance. The new instance re-runs the cache script against the updated
# model list.
#
resource "aws_instance" "cache_builder" {
  ami                         = data.aws_ami.al2023.id
  instance_type               = var.instance_type
  subnet_id                   = local.public_subnet_id
  associate_public_ip_address = true
  iam_instance_profile        = aws_iam_instance_profile.cache_builder.name
  vpc_security_group_ids      = [aws_security_group.cache_builder.id]

  # Root volume: 50 GB is sufficient for the scripts and OS.
  # Model weights go to EFS, not the root volume.
  root_block_device {
    volume_size = 50
    volume_type = "gp3"
    encrypted   = true
  }

  user_data = base64encode(templatefile(
    "${path.module}/templates/user_data.sh.tpl",
    {
      region                  = var.region
      efs_file_system_id      = local.efs_file_system_id
      efs_access_point_id     = local.efs_access_point_id
      assets_bucket           = local.assets_bucket
      models_json_key         = local.models_json_key
      cache_models_script_key = local.cache_models_key
      cache_model_script_key  = local.cache_model_key
      ssm_hf_token_name       = aws_ssm_parameter.hf_token.name
      prune_cache             = var.prune_cache ? "1" : "0"
      models_json_etag        = local.models_json_etag

      # TODO: i think these need exports in the 01/02 layers and locals here.
      ecr_registry = ?
      model_cache_image_uri = ? 
    }
  ))

  tags = merge(
    var.project_tags,
    {
      Name        = join("-", [var.org_name, var.project_name, var.env, "cache-builder"])
      GitTag      = var.git_tag
      ManagedBy   = "terraform"
    }
  )
}

output "cache_builder_instance_id" {
  description = "Instance ID of the cache builder. Use with: aws ssm start-session --target <id>"
  value       = aws_instance.cache_builder.id
}
