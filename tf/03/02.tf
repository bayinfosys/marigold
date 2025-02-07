# FIXME: pull these from the remote state outputs, rather than reference by name
data "aws_lambda_function" "models" {
  for_each = var.model_lambdas

  function_name = join("-", [var.org_name, var.project_name, var.env, replace(each.key, "/", "-")])

  tags = { Container = each.key }
}

data "aws_sfn_state_machine" "text_embedding" {
  name = join("-", [var.org_name, var.project_name, var.env, "text-embedding"])
}

data "aws_sfn_state_machine" "instruct" {
  name = join("-", [var.org_name, var.project_name, var.env, "instruct"])
}

data "aws_sfn_state_machine" "tts" {
  name = join("-", [var.org_name, var.project_name, var.env, "tts"])
}

data "aws_lambda_function" "instruct_polling" {
  function_name = join("-", [var.org_name, var.project_name, var.env, "instruct-polling"])
}

data "aws_lambda_function" "embed_polling" {
  function_name = join("-", [var.org_name, var.project_name, var.env, "embed-polling"])
}

data "aws_lambda_function" "tts_polling" {
  function_name = join("-", [var.org_name, var.project_name, var.env, "tts-polling"])
}

data "aws_lambda_function" "usage_stats" {
  function_name = join("-", [var.org_name, var.project_name, var.env, "usage-api"])
}

#
# external
#
data "aws_lambda_function" "authorizer_lambda" {
  function_name = join("-", [var.org_name, "vecdb", var.env, "rest-authorizer"])
}
