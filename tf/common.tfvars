org_name = "bayis"
project_name   = "vecmdl"
project_domain = "mdl.bayis.co.uk"

env = "dev"

available_models = {
  "sentence-transformers/all-minilm-l6-v2" = { model_type = "text-embedding" },
  "sentence-transformers/paraphrase-multilingual-mpnet-base-v2" = { model_type = "text-embedding" },
  "sentence-transformers/sentence-t5-large" = { model_type = "text-embedding" },

  "qwen/qwen2-0.5b-instruct" = { model_type = "instruct" },
  "qwen/qwen2-1.5b-instruct" = { model_type = "instruct" },
  "microsoft/phi-3-mini-128k-instruct" = { model_type = "instruct" },
  "meta-llama/llama-3.2-1b-instruct" = { model_type = "instruct" },
}

model_lambdas = {
  # text-embedding
  "embedding-paraphrase-multilingual-mpnet-base-v2" = {
    image = "environment"
    memory_size = 1024
    vector_size = 384
    timeout = 40
    environment_variables = {
      MODELNAME = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
      MODEL_TYPE = "text-embedding"
    }
    command = "models.text_embed.main.lambda_handler"
  },
  "embedding-sentence-t5-large" = {
    image = "environment"
    memory_size = 1024
    vector_size = 768
    timeout = 40
    environment_variables = {
      MODELNAME = "sentence-transformers/sentence-t5-large"
      MODEL_TYPE = "text-embedding"
    }
    command = "models.text_embed.main.lambda_handler"
  },
  "embedding-all-minilm-l6-v2" = {
    image = "environment"
    memory_size = 1024
    vector_size = 384
    timeout = 40
    environment_variables = {
      MODELNAME = "sentence-transformers/all-minilm-l6-v2"
      MODEL_TYPE = "text-embedding"
    }
    command = "models.text_embed.main.lambda_handler"
  },

  # instruct
  "qwen2-05b-instruct" = {
    image = "environment"
    memory_size = 4000
    environment_variables = {
      MODELNAME = "qwen/qwen2-0.5b-instruct"
      MODEL_TYPE = "instruct"
      LOW_CPU_MEM_USAGE = "1"
    }
    command = "models.instruct.main.lambda_handler"
  },
  "qwen2-15b-instruct" = {
    image = "environment"
    memory_size = 8000
    environment_variables = {
      MODELNAME = "qwen/qwen2-1.5b-instruct"
      MODEL_TYPE = "instruct"
      LOW_CPU_MEM_USAGE = "1"
    }
    command = "models.instruct.main.lambda_handler"
  },
  "microsoft-phi-3-mini-128k-instruct" = {
    image = "environment"
    memory_size = 8000
    environment_variables = {
      MODELNAME = "microsoft/phi-3-mini-128k-instruct"
      MODEL_TYPE = "instruct"
      LOW_CPU_MEM_USAGE = "1"
    }
    command = "models.instruct.main.lambda_handler"
  },
  "meta-llama-32-1b-instruct" = {
    image = "environment"
    memory_size = 8000
    environment_variables = {
      MODELNAME = "meta-llama/llama-3.2-1b-instruct"
      MODEL_TYPE = "instruct"
      LOW_CPU_MEM_USAGE = "1"
    }
    command = "models.instruct.main.lambda_handler"
  },

  # tts
  "mms-tts-eng" = {
    image = "environment"
    environment_variables = {
      MODELNAME = "facebook/mms-tts-eng"
      MODEL_TYPE = "tts"
    }
    command = "models.tts.main.lambda_handler"
  },
  "mms-tts-cym" = {
    image = "environment"
    environment_variables = {
      MODELNAME = "facebook/mms-tts-cym"
      MODEL_TYPE = "tts"
    }
    command = "models.tts.main.lambda_handler"
  },
  "mms-tts-deu" = {
    image = "environment"
    environment_variables = {
      MODELNAME = "facebook/mms-tts-deu"
      MODEL_TYPE = "tts"
    }
    command = "models.tts.main.lambda_handler"
  },
  "mms-tts-fra" = {
    image = "environment"
    environment_variables = {
      MODELNAME = "facebook/mms-tts-fra"
      MODEL_TYPE = "tts"
    }
    command = "models.tts.main.lambda_handler"
  },
  "mms-tts-spa" = {
    image = "environment"
    environment_variables = {
      MODELNAME = "facebook/mms-tts-spa"
      MODEL_TYPE = "tts"
    }
    command = "models.tts.main.lambda_handler"
  },
  "mms-tts-fin" = {
    image = "environment"
    environment_variables = {
      MODELNAME = "facebook/mms-tts-fin"
      MODEL_TYPE = "tts"
    }
    command = "models.tts.main.lambda_handler"
  },
  "mms-tts-nld" = {
    image = "environment"
    environment_variables = {
      MODELNAME = "facebook/mms-tts-nld"
      MODEL_TYPE = "tts"
    }
    command = "models.tts.main.lambda_handler"
  },
}
