# FIXME: pull these from the remote state outputs, rather than reference by name
data "aws_lambda_function" "polling_start_lambda_arn" {
  function_name = data.terraform_remote_state.pipelines.outputs["polling_lambda"]
}

#data "aws_lambda_function" "usage_stats" {
#  function_name = join("-", [var.org_name, var.project_name, var.env, "usage-fetch"])
#}

data "aws_s3_bucket" "assets" {
  bucket = data.terraform_remote_state.pipelines.outputs["asset_bucket_name"]
}

data "aws_s3_bucket" "results" {
  bucket = data.terraform_remote_state.pipelines.outputs["results_bucket"]
}

data "aws_s3_bucket" "model_outputs" {
  bucket = data.terraform_remote_state.pipelines.outputs["model_outputs_bucket_name"]
}

data "aws_lambda_function" "workflow_api_lambda" {
  function_name = data.terraform_remote_state.pipelines.outputs["workflow_api_lambda"]
}
