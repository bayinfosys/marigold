#
# export the models.json from the lambdas
#

# read pre-generated JSON file
data "local_file" "models_json" {
  filename = "${path.module}/../assets/models.json"
}

# parse the pre-generate data
locals {
  models_data = jsondecode(data.local_file.models_json.content)
}

# get the extra data from hf endpoint
data "external" "huggingface_model_info" {
  for_each = local.models_data

  program = ["bash", "${path.module}/../../scripts/build-model-info.sh", each.key]
}

# get the new hf supplements and merge with the pre-generated file
locals {
  models_extended_data = {
    for name in keys(local.models_data) : name => merge(
      local.models_data[name],  # Base model data
      data.external.huggingface_model_info[name].result,
      # override some of the huggingface data which needs recoding
      {
        tags           = try(jsondecode(data.external.huggingface_model_info[name].result.tags), [])
        parameter_count = try(tonumber(data.external.huggingface_model_info[name].result.parameter_count), 0)
      }
    )
  }
}

# save a local copy
resource "local_file" "models_json" {
  filename = "${path.module}/../assets/models_full.json"
  content  = jsonencode(local.models_extended_data)
}

#
# models.json public file
#
resource "aws_s3_object" "models_object" {
  bucket = data.aws_s3_bucket.assets.id
  key    = "models.json"

  content_type = "application/json"
  content  = jsonencode(local.models_extended_data)
}
