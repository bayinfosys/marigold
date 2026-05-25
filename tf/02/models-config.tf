resource "aws_s3_object" "models_config_internal" {
  bucket       = aws_s3_bucket.data.id
  key          = "models_config.json"
  content_type = "application/json"

  content = jsonencode({
    for name, conf in var.models : md5(conf.environment_variables["MODELNAME"]) => {
      queue_url       = aws_sqs_queue.model_queues[name].url
      model_name      = conf.environment_variables["MODELNAME"]
      task_definition = aws_ecs_task_definition.model[name].arn
      family          = aws_ecs_task_definition.model[name].family
      service_name    = aws_ecs_service.model[name].name
      model_type      = conf.environment_variables["MODEL_TYPE"]
      gpu_tier        = conf.gpu_tier
    }
  })
}
