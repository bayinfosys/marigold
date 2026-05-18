data "aws_lambda_function" "request_receiver" {
  function_name = data.terraform_remote_state.pipelines.outputs["request_receiver_lambda"]
}

#data "aws_lambda_function" "usage_stats" {
#  function_name = join("-", [var.org_name, var.project_name, var.env, "usage-fetch"])
#}

data "aws_s3_bucket" "assets" {
  bucket = data.terraform_remote_state.pipelines.outputs["asset_bucket_name"]
}

data "aws_s3_bucket" "model_outputs" {
  bucket = data.terraform_remote_state.pipelines.outputs["model_outputs_bucket_name"]
}

data "aws_lambda_function" "workflow_api_lambda" {
  function_name = data.terraform_remote_state.pipelines.outputs["workflow_api_lambda"]
}
