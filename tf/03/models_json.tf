#
# export the models.json from the lambdas
#
locals {
  processed_models = [
    for name, model in var.model_lambdas : {
      modelname = lookup(model.environment_variables, "MODELNAME", null)
      input     = replace(lookup(model.environment_variables, "MODEL_INPUT", ""), "MODEL_", "")
      output    = replace(lookup(model.environment_variables, "MODEL_OUTPUT", ""), "MODEL_", "")
    }
  ]
}

#
# models.json public file
#
resource "aws_s3_object" "models_object" {
  bucket = data.aws_s3_bucket.assets.id
  key    = "models.json"

  content_type = "application/json"
  content  = jsonencode(local.processed_models)
}
