#
# export the models.json from the lambdas data
#
locals {
  processed_models = {
    for name, model in var.model_lambdas :
    lookup(model.environment_variables, "MODELNAME", name) => {  # Use MODELNAME as key
      modelname = lookup(model.environment_variables, "MODELNAME", null)
      input     = replace(lookup(model.environment_variables, "MODEL_INPUT", ""), "MODEL_", "")
      output    = replace(lookup(model.environment_variables, "MODEL_OUTPUT", ""), "MODEL_", "")
      type      = replace(lookup(model.environment_variables, "MODEL_TYPE", ""), "MODEL_", "")
    } if lookup(model.environment_variables, "MODELNAME", null) != null  # Ensure key is valid
  }
}

resource "local_file" "models_json" {
  filename = "${path.module}/../assets/models.json"
  content  = jsonencode(local.processed_models)
  file_permission = "0644"
}
