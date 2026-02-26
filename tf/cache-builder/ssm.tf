#
# HuggingFace API token, stored as a SecureString in SSM Parameter Store.
# The EC2 instance reads this at runtime, so the token never appears in
# user_data or instance metadata.
#
# Supply the token at apply time:
#   make deploy/cache-builder HF_TOKEN=hf_xxxx
# or via environment variable:
#   export TF_VAR_hf_token=hf_xxxx
#   make deploy/cache-builder
#
# If no token is needed (all models are public), leave hf_token unset
# and the parameter will contain an empty string. The cache script
# only passes the token to models where hf_token_required: true.
#

resource "aws_ssm_parameter" "hf_token" {
  name        = join("/", ["", var.org_name, var.project_name, var.env, "hf-token"])
  description = "HuggingFace API token for downloading gated models"
  type        = "SecureString"
  value       = var.hf_token != "" ? var.hf_token : "not-set"

  tags = var.project_tags
}
