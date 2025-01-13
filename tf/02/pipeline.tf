locals {
  polling_dummy_pipeline_yaml = templatefile("${path.module}/pipelines/polling_dummy.yaml", {
    results_cache_table = aws_dynamodb_table.results_cache.id
  })

  text_embedding_pipeline_yaml = templatefile("${path.module}/pipelines/text_embedding.yaml", merge({
    for x in keys(var.model_lambdas) : x => module.model_lambdas[x].lambda_function_arn
    }, {
    results_cache_table = aws_dynamodb_table.results_cache.id
    }
  ))

  instruct_pipeline_yaml = templatefile("${path.module}/pipelines/instruct.yaml", merge({
    for x in keys(var.model_lambdas) : x => module.model_lambdas[x].lambda_function_arn
    }, {
    results_cache_table = aws_dynamodb_table.results_cache.id
    }
  ))

  tts_pipeline_yaml = templatefile("${path.module}/pipelines/tts.yaml", {
    for x in keys(var.model_lambdas) : x => module.model_lambdas[x].lambda_function_arn
  })

  # convert the yaml to json for aws
  polling_dummy_pipeline_json = yamldecode(local.polling_dummy_pipeline_yaml)
  text_embedding_pipeline_json = yamldecode(local.text_embedding_pipeline_yaml)
  instruct_pipeline_json       = yamldecode(local.instruct_pipeline_yaml)
  tts_pipeline_json            = yamldecode(local.tts_pipeline_yaml)
}

module "polling_dummy" {
  source = "terraform-aws-modules/step-functions/aws"

  name = join("-", [var.org_name, var.project_name, var.env, "polling-dummy"])

  definition = jsonencode(local.polling_dummy_pipeline_json)

#  type = "EXPRESS"

  service_integrations = {
    dynamodb = {
      dynamodb = [aws_dynamodb_table.results_cache.arn]
    }
  }

  logging_configuration = {
    include_execution_data = true
    level                  = "ALL"
  }

  tags = var.project_tags
}


module "text_embedding" {
  source = "terraform-aws-modules/step-functions/aws"

  name = join("-", [var.org_name, var.project_name, var.env, "text-embedding"])

  definition = jsonencode(local.text_embedding_pipeline_json)

#  type = "EXPRESS"

  service_integrations = {
    lambda = {
      lambda = [for k, v in module.model_lambdas : v.lambda_function_arn]
    }

    dynamodb = {
      dynamodb = [aws_dynamodb_table.results_cache.arn]
    }
  }

  logging_configuration = {
    include_execution_data = true
    level                  = "ALL"
  }

  tags = var.project_tags
}

module "instruct" {
  source = "terraform-aws-modules/step-functions/aws"

  name = join("-", [var.org_name, var.project_name, var.env, "instruct"])

  definition = jsonencode(local.instruct_pipeline_json)

  type = "EXPRESS"

  service_integrations = {
    lambda = {
      lambda = [for k, v in module.model_lambdas : v.lambda_function_arn]
    }

    dynamodb = {
      dynamodb = [aws_dynamodb_table.results_cache.arn]
    }
  }

  logging_configuration = {
    include_execution_data = true
    level                  = "ALL"
  }

  tags = var.project_tags
}

module "tts" {
  source = "terraform-aws-modules/step-functions/aws"

  name = join("-", [var.org_name, var.project_name, var.env, "tts"])

  definition = jsonencode(local.tts_pipeline_json)

  type = "EXPRESS"

  service_integrations = {
    lambda = {
      lambda = [for k, v in module.model_lambdas : v.lambda_function_arn]
    }
  }

  logging_configuration = {
    include_execution_data = true
    level                  = "ALL"
  }

  tags = var.project_tags
}
