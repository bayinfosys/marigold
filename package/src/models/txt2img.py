"""Text-to-image generation.

Takes a text prompt and returns a generated image written to S3.

Uses diffusers DiffusionPipeline. Compatible with any model loadable via
cache_model.load_txt2img (i.e. any diffusers-compatible checkpoint).

NUM_STEPS defaults to 10; override per-model via extra_env in models.yaml.
"""

import logging
import os
from time import perf_counter as clock

import numpy as np
import torch
from api.models import ModelType, Txt2ImgRequest, Txt2ImgResponse
from models import BaseModelHandler
from models.cache_model import load_txt2img
from PIL import Image
from shared import image_to_png_bytes, record_usage, write_binary_output

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

OUTPUT_BUCKET = os.environ["OUTPUT_BUCKET"]


class Txt2ImgModel(BaseModelHandler):

    def __init__(self, modelname: str):
        super().__init__(modelname)
        self.num_steps = int(os.getenv("NUM_STEPS", "10"))

        _T = clock()
        self.pipe = load_txt2img(modelname)
        logger.info("'%s' loaded in %0.2fs", modelname, clock() - _T)

    def process(self, user_id: str, message_id: str, request: dict) -> Txt2ImgResponse:
        req = Txt2ImgRequest.model_validate(request)
        return self._run(user_id, message_id, req)

    def _run(
        self, user_id: str, message_id: str, request: Txt2ImgRequest
    ) -> Txt2ImgResponse:
        num_steps = request.num_inference_steps or self.num_steps

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

        image_mimetype = "image/png"
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

        output_reference = write_binary_output(
            message_id=message_id,
            model_type=ModelType.TXT2IMG,
            field_name="image",
            data=image_bytes,
            mimetype=image_mimetype,
            bucket=OUTPUT_BUCKET,
        )

        usage = record_usage(
            user_id, ModelType.TXT2IMG, self.modelname, duration, iduration
        )

        return Txt2ImgResponse(
            model=self.modelname,
            usage=usage,
            outputs={"image": output_reference},
        )
