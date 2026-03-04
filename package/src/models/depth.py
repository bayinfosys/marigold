"""Monocular depth estimation.

Takes a single image and returns a depth map written to S3.

Compatible models:
    facebook/dpt-dinov2-small-kitti
"""

import logging
import os
from time import perf_counter as clock

import torch
from PIL import Image

from shared.enums import ModelMode, ModelType, OutputMimeType
from shared.outputs import decode_image, image_to_png_bytes
from shared.registry import BaseModelHandler, OutputField, model_spec
from shared.usage import record_usage
from models.standard_loader import ModelLoaderResult, standard_loader
from api.models import DepthRequest, DepthResponse

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)


def load_depth(modelname: str, **kwargs) -> ModelLoaderResult:
    """Monocular depth estimation."""
    from transformers import AutoImageProcessor as T
    from transformers import AutoModelForDepthEstimation as M

    return standard_loader(T, M, modelname, **kwargs)


@model_spec(
    model_type=ModelType.DEPTH,
    mode=ModelMode.GEN,
    output_fields=[OutputField(name="depth", mimetype=OutputMimeType.IMAGE_PNG)],
    loader=load_depth,
    request_model=DepthRequest,
    response_model=DepthResponse,
    route="/gen/depth",
)
class DepthModel(BaseModelHandler):

    def __init__(self, modelname: str):
        super().__init__(modelname)

    def _run(self, user_id: str, message_id: str, request: DepthRequest) -> DepthResponse:
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

        output_reference = self.write_output("depth", depth_bytes, message_id)

        usage = record_usage(
            user_id=user_id,
            model_type=ModelType.DEPTH,
            modelname=self.modelname,
            duration=duration,
            inference=iduration,
        )

        return DepthResponse(
            model=self.modelname,
            usage=usage,
            outputs={"depth": output_reference},
        )
