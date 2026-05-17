#
# Expand subnet CIDR lists into per-entry maps, since aws_vpc_security_group_ingress_rule
# accepts a single cidr_ipv4, not a list.
#
locals {
  efs_ingress_private = {
    for idx, cidr in module.vpc.private_subnets_cidr_blocks :
    "private_subnet_access_${idx}" => {
      description = "NFS ingress from private subnet ${cidr}"
      cidr_ipv4   = cidr
    }
  }

  efs_ingress_public = {
    for idx, cidr in module.vpc.public_subnets_cidr_blocks :
    "public_subnet_access_${idx}" => {
      description = "NFS ingress from public subnet ${cidr}"
      cidr_ipv4   = cidr
    }
  }
}

module "efs" {
  source = "terraform-aws-modules/efs/aws"

  name = join("-", [var.org_name, var.project_name, var.env, "efs"])

  # file system policy
  attach_policy = true

  policy_statements = {
    AllowMountAndWrite = {
     sid    = "AllowMountAndWrite"
      effect = "Allow"
      actions = [
        "elasticfilesystem:ClientMount",
        "elasticfilesystem:ClientWrite",
      ]
      principals = [
       {
          type = "AWS"
          # TODO(prod): replace wildcard with explicit role ARNs.
          # Required principals:
          #   - The ECS task role (aws_iam_role.model_task.arn) for read access
          #   - The cache builder EC2 instance role ARN for write access
          # Using "*" currently relies on the access point IAM policy for enforcement,
          # which is correct but defence-in-depth suggests scoping the FS policy too.
          identifiers = ["*"]
        }
      ]
    }
  }

  # mount targets - one for each az
  mount_targets = {
    for idx, subnet_id in module.vpc.private_subnets :
    "az-${idx}" => { subnet_id = subnet_id }
  }

  # security group
  security_group_description = join("-", [var.org_name, var.project_name, var.env, "efs-access-sg"])
  security_group_vpc_id      = module.vpc.vpc_id

  security_group_ingress_rules = merge(
    local.efs_ingress_private,
    local.efs_ingress_public,
  )

  # access points
  access_points = {
    assets_rw = {
      posix_user = {
        gid = 1000
        uid = 1000
      }
      root_directory = {
        path = "/cache"
        creation_info = {
          owner_gid   = 1000
          owner_uid   = 1000
          permissions = "777"
        }
      }
    }

    assets_ro = {
      posix_user = {
        gid = 1000
        uid = 1000
      }
      root_directory = {
        path = "/cache"
        creation_info = {
          owner_gid   = 1000
          owner_uid   = 1000
          permissions = "755"
        }
      }
    }
  }

  # in elastic throughput mode we often get throttled, so try this.
  throughput_mode = "elastic"

  # disable backup policy entirely - models can be recreated from HuggingFace
  create_backup_policy = false
  enable_backup_policy = false

  create_replication_configuration = false

  tags = var.project_tags
}

#
# Read-only IAM policy for ecs attachment
#
data "aws_iam_policy_document" "efs_ro_access" {
  statement {
    actions = [
      "elasticfilesystem:ClientMount",
      "elasticfilesystem:ClientRead",
    ]
    resources = [module.efs.access_points["assets_ro"].arn]
  }
}

resource "aws_iam_policy" "efs_access_policy" {
  name        = join("-", [var.org_name, var.project_name, var.env, "efs-ro-access"])
  description = "Read-only access to EFS assets access point"
  policy      = data.aws_iam_policy_document.efs_ro_access.json
}
