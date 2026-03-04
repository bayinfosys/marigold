"""Image segmentation / mask generation.

Takes an image and returns a segmentation mask written to S3.

Compatible models:
    facebook/sam-vit-huge
    facebook/sam-vit-large
    facebook/sam-vit-base
"""

import logging
import os
from time import perf_counter as clock

import numpy as np
import torch
from PIL import Image

from shared.enums import ModelMode, ModelType, OutputMimeType
from shared.outputs import decode_image, image_to_png_bytes
from shared.registry import BaseModelHandler, OutputField, model_spec
from shared.usage import record_usage
from models.standard_loader import ModelLoaderResult, standard_loader
from api.models import Img2MaskRequest, Img2MaskResponse

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)


def load_img2mask(modelname: str, **kwargs) -> ModelLoaderResult:
    """Image segmentation / mask generation."""
    from transformers import AutoModelForMaskGeneration as M
    from transformers import AutoProcessor as T

    return standard_loader(T, M, modelname, **kwargs)


@model_spec(
    model_type=ModelType.IMG2MASK,
    mode=ModelMode.GEN,
    output_fields=[OutputField(name="mask", mimetype=OutputMimeType.IMAGE_PNG)],
    loader=load_img2mask,
    request_model=Img2MaskRequest,
    response_model=Img2MaskResponse,
    route="/gen/img2mask",
)
class Img2MaskModel(BaseModelHandler):

    def __init__(self, modelname: str):
        super().__init__(modelname)

    def _run(
        self, user_id: str, message_id: str, request: Img2MaskRequest
    ) -> Img2MaskResponse:
        T = clock()

        try:
            image = decode_image(request.input)
        except Exception as e:
            logger.error(
                "[%s/%s] failed to decode input image [%s]", user_id, message_id, str(e)
            )
            raise ValueError("invalid image input") from e

        logger.info(
            "[%s/%s] segmenting image %s mode=%s",
            user_id,
            message_id,
            str(image.size),
            image.mode,
        )

        inputs = self.processor(images=image, return_tensors="pt")

        T1 = clock()
        with torch.no_grad():
            outputs = self.model(**inputs)
        iduration = clock() - T1

        masks = self.processor.image_processor.post_process_masks(
            outputs.pred_masks.cpu(),
            inputs["original_sizes"].cpu(),
            inputs["reshaped_input_sizes"].cpu(),
        )

        # Collapse masks to a single-channel label image: each pixel takes
        # the index of the highest-confidence mask at that location.
        mask_stack = masks[0].squeeze().cpu().numpy()  # (N, H, W)
        if mask_stack.ndim == 2:
            mask_stack = mask_stack[np.newaxis, ...]
        label_map = mask_stack.argmax(axis=0).astype("uint8")
        scaled = (label_map * 255 // max(mask_stack.shape[0] - 1, 1)).astype("uint8")
        label_image = Image.fromarray(scaled)
        mask_bytes = image_to_png_bytes(label_image)
        duration = clock() - T

        logger.info(
            "[%s/%s] '%s' mask %s in %0.2fs (inference %0.2fs)",
            user_id,
            message_id,
            self.modelname,
            str(label_image.size),
            duration,
            iduration,
        )

        output_reference = self.write_output("mask", mask_bytes, message_id)

        usage = record_usage(
            user_id=user_id,
            model_type=ModelType.IMG2MASK,
            modelname=self.modelname,
            duration=duration,
            inference=iduration,
        )

        return Img2MaskResponse(
            model=self.modelname,
            usage=usage,
            outputs={"mask": output_reference},
        )
