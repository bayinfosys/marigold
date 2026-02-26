"""Monocular depth estimation.

Takes a single image and returns a depth map written to S3.

Compatible models:
    facebook/dpt-dinov2-small-kitti
"""

import logging
import os
from time import perf_counter as clock

import torch
from api.models import DepthRequest, DepthResponse, ModelType
from models import BaseModelHandler
from models.cache_model import load_depth
from PIL import Image
from shared import (decode_image, image_to_png_bytes, record_usage,
                    write_binary_output)

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

OUTPUT_BUCKET = os.environ["OUTPUT_BUCKET"]


# ---------------------------------------------------------------------------
# Request / response types
#
# DepthRequest and DepthResponse live in api.models. They are defined as:
#
#   class DepthRequest(BaseModel):
#       model: str
#       input: str   # base64-encoded input image, any PIL-readable format
#
#   class DepthResponse(BaseModel):
#       model: str
#       usage: ModelUsageStats
#       outputs: Dict[str, OutputReference]  # key "depth"
#
# Add these to api/models.py alongside the other binary-output types.
# ---------------------------------------------------------------------------


class DepthModel(BaseModelHandler):

    def __init__(self, modelname: str):
        super().__init__(modelname)
        _T = clock()
        self.processor, self.model = load_depth(modelname)
        logger.info("'%s' loaded in %0.2fs", modelname, clock() - _T)

    def process(self, user_id: str, message_id: str, request: dict):
        req = DepthRequest.model_validate(request)
        return self._run(user_id, message_id, req)

    def _run(self, user_id: str, message_id: str, request) -> object:
        T = clock()

        try:
            image = decode_image(request.input)
        except Exception as e:
            logger.error(
                "[%s/%s] failed to decode input image [%s]", user_id, message_id, str(e)
            )
            raise ValueError("invalid image input") from e

        inputs = self.processor(images=image, return_tensors="pt")

        T1 = clock()
        with torch.no_grad():
            outputs = self.model(**inputs)
            predicted_depth = outputs.predicted_depth
        iduration = clock() - T1

        # interpolate depth map to match the original image dimensions
        depth_map = torch.nn.functional.interpolate(
            predicted_depth.unsqueeze(1),
            size=image.size[::-1],
            mode="bicubic",
            align_corners=False,
        )

        arr = depth_map.squeeze().cpu().numpy()
        normalised = (arr * 255.0 / arr.max()).astype("uint8")
        depth_image = Image.fromarray(normalised)
        depth_bytes = image_to_png_bytes(depth_image)

        depth_mimetype = "image/png"
        duration = clock() - T

        logger.info(
            "[%s/%s] '%s' depth map %s in %0.2fs (inference %0.2fs)",
            user_id,
            message_id,
            self.modelname,
            str(depth_image.size),
            duration,
            iduration,
        )

        output_reference = write_binary_output(
            message_id=message_id,
            model_type=ModelType.DEPTH,
            field_name="depth",
            data=depth_bytes,
            mimetype=depth_mimetype,
            bucket=OUTPUT_BUCKET,
        )

        usage = record_usage(
            user_id, ModelType.DEPTH, self.modelname, duration, iduration
        )

        return DepthResponse(
            model=self.modelname,
            usage=usage,
            outputs={"depth": output_reference},
        )
