from api.models import ModelType, ModelModalities, ModelDescription, ModelProvider

INSTRUCT_MODELS = [
  ModelDescription(
    name="qwen/qwen2-05b-instruct",
    type=ModelType.INSTRUCT,
    description="Qwen2 is the new series of Qwen large language models. For Qwen2, we release a number of base language models and instruction-tuned language models ranging from 0.5 to 72 billion parameters, including a Mixture-of-Experts model. This repo contains the instruction-tuned 0.5B Qwen2 model.",
    provider=ModelProvider(name="qwen", description="large language models created by Alibaba Cloud", links={"org": "https://huggingface.co/Qwen", "model": "https://huggingface.co/Qwen/Qwen2-0.5B-Instruct"}),
    inputs=[ModelModalities.TEXT],
    outputs=[ModelModalities.TEXT]
  ),
  ModelDescription(
    name="qwen/qwen2-15b-instruct",
    type=ModelType.INSTRUCT,
    description="Qwen2 is the new series of Qwen large language models. For Qwen2, we release a number of base language models and instruction-tuned language models ranging from 0.5 to 72 billion parameters, including a Mixture-of-Experts model. This repo contains the instruction-tuned 0.5B Qwen2 model.",
    provider=ModelProvider(name="qwen", description="large language models created by Alibaba Cloud", links={"org": "https://huggingface.co/Qwen", "model": "https://huggingface.co/Qwen/Qwen2-0.5B-Instruct"}),
    inputs=[ModelModalities.TEXT],
    outputs=[ModelModalities.TEXT]
  ),
  ModelDescription(
    name="microsoft/phi-3-mini-128k-instruct",
    type=ModelType.INSTRUCT,
    description="The Phi-3-Mini-128K-Instruct is a 3.8 billion-parameter, lightweight, state-of-the-art open model trained using the Phi-3 datasets. This dataset includes both synthetic data and filtered publicly available website data, with an emphasis on high-quality and reasoning-dense properties.",
    provider=ModelProvider(name="microsoft", description="multi-modal models created by microsoft", links={"org": "https://azure.microsoft.com/en-us/products/phi-3", "model": "https://huggingface.co/microsoft/Phi-3-mini-128k-instruct"}),
    inputs=[ModelModalities.TEXT, ModelModalities.IMAGE],
    outputs=[ModelModalities.TEXT]
  )
]
