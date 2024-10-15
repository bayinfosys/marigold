#
# efs
# we store models and packages in a mounted efs disk
# which is attached to the lambda functions (readonly)
# it is populated by an ec2 instance (write)
#
module "efs" {
  source = "terraform-aws-modules/efs/aws"

  # file system
  name = join("-", [var.org_name, var.project_name, var.env, "efs"])

  # file system policy
  attach_policy = true
  policy_statements = [
    {
      sid    = "Example"
      effect = "Allow"

      actions = [
        "elasticfilesystem:ClientMount",
        "elasticfilesystem:ClientWrite",
      ]

      principals = [
        {
          type        = "AWS"
          identifiers = ["*"]
        }
      ]
    }
  ]

  # mount target
  # TODO: what is a mount target? i think it's the point the efs is hosted in the vpc
  # NB: we are all in eu-west-2a for the moment
  mount_targets = {
    "main" = {
      subnet_id = module.vpc.private_subnets[0]
    }
  }

  # security group
  security_group_description = join("-", [var.org_name, var.project_name, var.env, "efs-access-sg"])

  security_group_vpc_id = module.vpc.vpc_id
  security_group_rules = {
    private_subnet_access = {
      description = "ingress from private subnets"
      cidr_blocks = module.vpc.private_subnets_cidr_blocks
    }

    public_subnet_access = {
      description = "ingress from public subnets"
      cidr_blocks = module.vpc.public_subnets_cidr_blocks
    }
  }

  # access point(s) for read/write at the root
  # TODO: create access points for different subdirs?
  # NB: lambdas can only mount a single efs
  # NB: if paths are fs root, the posix_user is not applied
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

  # no backup (we can just recreate)
  enable_backup_policy = false

  # no replication
  create_replication_configuration = false

  tags = var.project_tags
}

#
# read only access policy
#
data "aws_iam_policy_document" "efs_ro_access" {
  statement {
    actions = [
      "elasticfilesystem:ClientMount",
      "elasticfilesystem:ClientRead"
    ]

    resources = [module.efs.access_points["assets_ro"].arn]
  }
}

resource "aws_iam_policy" "efs_access_policy" {
  name        = "efs-access-policy"
  description = "Policy for accessing EFS in read-only mode"

  policy = data.aws_iam_policy_document.efs_ro_access.json
}
