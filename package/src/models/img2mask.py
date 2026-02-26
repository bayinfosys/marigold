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
from api.models import Img2MaskRequest, Img2MaskResponse, ModelType
from models import BaseModelHandler
from models.cache_model import load_img2mask
from PIL import Image
from shared import (decode_image, image_to_png_bytes, record_usage,
                    write_binary_output)

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

OUTPUT_BUCKET = os.environ["OUTPUT_BUCKET"]


class Img2MaskModel(BaseModelHandler):

    def __init__(self, modelname: str):
        super().__init__(modelname)
        _T = clock()
        self.processor, self.model = load_img2mask(modelname)
        logger.info("'%s' loaded in %0.2fs", modelname, clock() - _T)

    def process(self, user_id: str, message_id: str, request: dict) -> Img2MaskResponse:
        req = Img2MaskRequest.model_validate(request)
        return self._run(user_id, message_id, req)

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

        mask_mimetype = "image/png"
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

        output_reference = write_binary_output(
            message_id=message_id,
            model_type=ModelType.IMG2MASK,
            field_name="mask",
            data=mask_bytes,
            mimetype=mask_mimetype,
            bucket=OUTPUT_BUCKET,
        )

        usage = record_usage(
            user_id, ModelType.IMG2MASK, self.modelname, duration, iduration
        )

        return Img2MaskResponse(
            model=self.modelname, usage=usage, outputs={"mask": output_reference}
        )
