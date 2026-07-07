"""Text-to-image generation.

Takes a text prompt and returns a generated image written to S3.

Uses diffusers DiffusionPipeline. Compatible with any diffusers-compatible
checkpoint. The pipeline is stored as both self.model (base class contract)
and self.pipe (local alias used in _run).

NUM_STEPS defaults to 10; override per-model via extra_env in models.yaml.
"""

import logging
import os
import json
from time import perf_counter as clock

import numpy as np
import torch
from api.models import Txt2ImgRequest, Txt2ImgResponse
from models.standard_loader import ModelLoaderResult
from PIL import Image
from shared.enums import ModelMode, ModelType, OutputMimeType
from shared.outputs import image_to_png_bytes
from shared.registry import BaseModelHandler, OutputField, model_spec
from shared.usage import build_usage

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)


def _make_quant_config(modelname: str) -> "PipelineQuantizationConfig | None":
    """Return a PipelineQuantizationConfig for 4-bit NF4 quantisation.

    Components are resolved in order:
      1. DIFFUSERS_QUANT_COMPONENTS env var -- comma-separated list,
         set per-model via extra_env in models.yaml
      2. Known model prefix table
      3. Default: ["transformer"]

    diffusers components (transformer, unet) receive DiffusersBitsAndBytesConfig.
    transformers components (text_encoder*) receive TransformersBitsAndBytesConfig.
    """
    from diffusers import BitsAndBytesConfig as DiffusersBitsAndBytesConfig
    from diffusers.quantizers import PipelineQuantizationConfig
    from transformers import BitsAndBytesConfig as TransformersBitsAndBytesConfig

    _DIFFUSERS_COMPONENTS  = {"transformer", "unet", "vae"}
    _TRANSFORMERS_COMPONENTS = {"text_encoder", "text_encoder_2", "text_encoder_3"}

    _COMPONENT_DEFAULTS = {
        "black-forest-labs/flux":          ["transformer", "text_encoder_2"],
        "stabilityai/stable-diffusion-3":  ["transformer", "text_encoder_3"],
        "stabilityai/stable-diffusion-xl": ["unet"],
        "tongyi-mai/z-image-turbo":        ["unet"],   # unconfirmed; assumed SDXL
    }

    env_val = os.getenv("DIFFUSERS_QUANT_COMPONENTS", "").strip()
    if env_val:
        components = [c.strip() for c in env_val.split(",") if c.strip()]
    else:
        components = None
        for prefix, names in _COMPONENT_DEFAULTS.items():
            if modelname.lower().startswith(prefix):
                components = names
                break
        if not components:
            components = ["transformer"]

    logger.info("quantisation components for '%s': %s", modelname, components)

    quant_mapping = {}
    for component in components:
        if component in _DIFFUSERS_COMPONENTS:
            quant_mapping[component] = DiffusersBitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=torch.bfloat16,
            )
        elif component in _TRANSFORMERS_COMPONENTS:
            quant_mapping[component] = TransformersBitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=torch.bfloat16,
            )
        else:
            logger.warning(
                "unknown component '%s' for '%s'; skipping", component, modelname
            )

    return PipelineQuantizationConfig(quant_mapping=quant_mapping)


def load_txt2img(modelname: str, cache_dir: str = None, **kwargs) -> ModelLoaderResult:
    """Text-to-image via diffusers DiffusionPipeline.

    Loads in float16 and places on GPU if available, CPU otherwise.
    Uses device_map="balanced" when accelerate is present and multiple
    GPUs are available (e.g. g5.12xlarge with 4x A10G).

    Returns a ModelLoaderResult with processor=None. The pipeline is stored
    in the model field and accessed via self.pipe in the handler.
    """
    from diffusers import DiffusionPipeline

    has_cuda   = torch.cuda.is_available()
    gpu_count  = torch.cuda.device_count() if has_cuda else 0
    load_in_4bit     = kwargs.get("load_in_4bit", False)
    dtype      = torch.float16 if has_cuda else torch.bfloat16
    local_files_only = os.getenv("HF_HUB_OFFLINE", "true").lower() != "0"

    logger.info("loading '%s' -- cuda=%s gpus=%d dtype=%s", modelname, has_cuda, gpu_count, dtype)

    T0 = clock()

    load_kwargs = dict(
        cache_dir        = cache_dir,
        torch_dtype      = dtype,
        local_files_only = local_files_only,
    )

    quant_config = _make_quant_config(modelname) if (load_in_4bit and has_cuda) else None

    if quant_config is not None:
        load_kwargs["quantization_config"] = quant_config
        pipe = DiffusionPipeline.from_pretrained(modelname, **load_kwargs)

        quant_names = set(quant_config.quant_mapping.keys())

        # build per-component target device
        # DIFFUSERS_DEVICE_MAP: json mapping component name to device string
        # e.g. '{"transformer": "cuda:0", "text_encoder": "cuda:1"}'
        # components absent from the map default to cuda:0
        explicit_map = {}
        env_map = os.getenv("DIFFUSERS_DEVICE_MAP", "").strip()
        if env_map:
            import json
            explicit_map = json.loads(env_map)

        for name, component in pipe.components.items():
            if not isinstance(component, torch.nn.Module):
                continue
            if name in quant_names:
                # quantised components: move to their target device
                # bitsandbytes places them on cpu after from_pretrained
                # without a device_map; move them explicitly here
                target = explicit_map.get(name, "cuda:0")
            else:
                target = explicit_map.get(name, "cuda:0")
            component.to(target)

    logger.info("loaded '%s' pipeline in %0.2fs", modelname, clock() - T0)
    return ModelLoaderResult(processor=None, model=pipe)


@model_spec(
    model_type=ModelType.TXT2IMG,
    mode=ModelMode.GEN,
    output_fields=[OutputField(name="image", mimetype=OutputMimeType.IMAGE_PNG)],
    loader=load_txt2img,
    request_model=Txt2ImgRequest,
    response_model=Txt2ImgResponse,
    route="/gen/txt2img",
)
class Txt2ImgModel(BaseModelHandler):

    def __init__(self, modelname: str):
        super().__init__(modelname)
        self.pipe = self.model
        self.num_steps = int(os.getenv("NUM_STEPS", "10"))

    def unload(self) -> None:
        del self.pipe
        super().unload()

    def _run(
        self, user_id: str, message_id: str, request: Txt2ImgRequest
    ) -> Txt2ImgResponse:
        num_steps = request.num_inference_steps if request.num_inference_steps is not None else self.num_steps

        logger.info(
            "[%s/%s] generating image: prompt='%s' steps=%i",
            user_id,
            message_id,
            request.prompt[:80],
            num_steps,
        )

        T = clock()

        pipe_kwargs = dict(
            prompt=request.prompt,
            num_inference_steps=num_steps,
            guidance_scale=request.guidance_scale,
            output_type="np",
        )
        if request.negative_prompt:
            pipe_kwargs["negative_prompt"] = request.negative_prompt
        if request.seed is not None:
            pipe_kwargs["generator"] = torch.Generator().manual_seed(request.seed)

        result = self.pipe(**pipe_kwargs)
        iduration = clock() - T

        image_arr = result.images[0]
        image = Image.fromarray(np.uint8(image_arr * 255.0))
        image_bytes = image_to_png_bytes(image)
        duration = clock() - T

        logger.info(
            "[%s/%s] '%s' generated %s in %0.2fs (inference %0.2fs)",
            user_id,
            message_id,
            self.modelname,
            str(image_arr.shape),
            duration,
            iduration,
        )

        output_reference = self.write_output("image", image_bytes, message_id)

        usage = build_usage(
            user_id=user_id,
            model_type=ModelType.TXT2IMG,
            modelname=self.modelname,
            duration=duration,
            inference=iduration,
            load_time_ms=self.load_time_ms,
            model_size_bytes=self.model_size_bytes,
        )

        return Txt2ImgResponse(
            model=self.modelname,
            usage=usage,
            outputs={"image": output_reference},
        )
