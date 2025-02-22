org_name = "bayis"
project_name   = "vecmdl"
project_domain = "mdl.bayis.co.uk"

env = "dev"

model_lambdas = {
  # text-embedding
  "embedding-paraphrase-multilingual-mpnet-base-v2" = {
    image = "environment"
    memory_size = 2048
    vector_size = 384
    environment_variables = {
      MODELNAME = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
      MODEL_TYPE = "text-embedding"
      MODEL_INPUT = "text"
      MODEL_OUTPUT = "vector/384"
    }
    command = "models.text_embed.main.lambda_handler"
  },
  "embedding-sentence-t5-large" = {
    image = "environment"
    memory_size = 2048
    vector_size = 768
    environment_variables = {
      MODELNAME = "sentence-transformers/sentence-t5-large"
      MODEL_TYPE = "text-embedding"
      MODEL_INPUT = "text"
      MODEL_OUTPUT = "vector/768"
    }
    command = "models.text_embed.main.lambda_handler"
  },
  "embedding-all-minilm-l6-v2" = {
    image = "environment"
    memory_size = 2048
    vector_size = 384
    environment_variables = {
      MODELNAME = "sentence-transformers/all-minilm-l6-v2"
      MODEL_TYPE = "text-embedding"
      MODEL_INPUT = "text"
      MODEL_OUTPUT = "vector/384"
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
      MODEL_INPUT = "chat"
      MODEL_OUTPUT = "chat"
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
      MODEL_INPUT = "chat"
      MODEL_OUTPUT = "chat"
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
      MODEL_INPUT = "chat"
      MODEL_OUTPUT = "chat"
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
      MODEL_INPUT = "chat"
      MODEL_OUTPUT = "chat"
    }
    command = "models.instruct.main.lambda_handler"
  },

  # tts
  "mms-tts-eng" = {
    image = "environment"
    environment_variables = {
      MODELNAME = "facebook/mms-tts-eng"
      MODEL_TYPE = "tts"
      MODEL_INPUT = "text"
      MODEL_OUTPUT = "speech"
      MODEL_LANGCODE = "en/GB"
    }
    command = "models.tts.main.lambda_handler"
  },
  "mms-tts-cym" = {
    image = "environment"
    environment_variables = {
      MODELNAME = "facebook/mms-tts-cym"
      MODEL_TYPE = "tts"
      MODEL_INPUT = "text"
      MODEL_OUTPUT = "speech"
      MODEL_LANGCODE = "cy/GB"
    }
    command = "models.tts.main.lambda_handler"
  },
  "mms-tts-deu" = {
    image = "environment"
    environment_variables = {
      MODELNAME = "facebook/mms-tts-deu"
      MODEL_TYPE = "tts"
      MODEL_INPUT = "text"
      MODEL_OUTPUT = "speech"
      MODEL_LANGCODE = "de/DE"
    }
    command = "models.tts.main.lambda_handler"
  },
  "mms-tts-fra" = {
    image = "environment"
    environment_variables = {
      MODELNAME = "facebook/mms-tts-fra"
      MODEL_TYPE = "tts"
      MODEL_INPUT = "text"
      MODEL_OUTPUT = "speech"
      MODEL_LANGCODE = "fr/FR"
    }
    command = "models.tts.main.lambda_handler"
  },
  "mms-tts-spa" = {
    image = "environment"
    environment_variables = {
      MODELNAME = "facebook/mms-tts-spa"
      MODEL_TYPE = "tts"
      MODEL_INPUT = "text"
      MODEL_OUTPUT = "speech"
      MODEL_LANGCODE = "es/ES"
    }
    command = "models.tts.main.lambda_handler"
  },
  "mms-tts-fin" = {
    image = "environment"
    environment_variables = {
      MODELNAME = "facebook/mms-tts-fin"
      MODEL_TYPE = "tts"
      MODEL_INPUT = "text"
      MODEL_OUTPUT = "speech"
      MODEL_LANGCODE = "fi/FI"
    }
    command = "models.tts.main.lambda_handler"
  },
  "mms-tts-nld" = {
    image = "environment"
    environment_variables = {
      MODELNAME = "facebook/mms-tts-nld"
      MODEL_TYPE = "tts"
      MODEL_INPUT = "text"
      MODEL_OUTPUT = "speech"
      MODEL_LANGCODE = "nl/NL"
    }
    command = "models.tts.main.lambda_handler"
  },

  "facebook-dpt-dinov2-small-kitti" = {
    image = "environment"
    environment_variables = {
      MODELNAME = "facebook/dpt-dinov2-small-kitti"
      MODEL_TYPE = "depth"
      MODEL_INPUT = "image"
      MODEL_OUTPUT = "depth"
    }
    command = "models.depth.main.lambda_handler"
  },

  "facebook-sam-vit-huge" = {
    image = "environment"
    environment_variables = {
      MODELNAME = "facebook/sam-vit-huge"
      MODEL_TYPE = "segmentation"
      MODEL_INPUT = "image"
      MODEL_OUTPUT = "labels"
    }
    command = "models.img2mask.main.lambda_handler"
  },
}
