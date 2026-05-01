"""Image evaluation models.

Scores a single image against model-specific metrics. Labels and their
meanings depend on the checkpoint -- an NSFW detector returns
safe/unsafe probabilities, an aesthetic predictor returns quality scores.
Labels are taken from the model's own config.id2label mapping.

Compatible models:
    Falconsai/nsfw_image_detection
    cafeai/cafe_aesthetic
"""

import logging
import os
from time import perf_counter as clock

import torch

from shared.enums import ModelMode, ModelType
from shared.outputs import decode_image
from shared.registry import BaseModelHandler, model_spec
from shared.usage import record_usage
from models.standard_loader import ModelLoaderResult, standard_loader
from api.models import EvalImageRequest, EvalResponse, EvalScore

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)


def load_image_eval(modelname: str, **kwargs) -> ModelLoaderResult:
    """Image classification models for image scoring."""
    from transformers import AutoImageProcessor as T
    from transformers import AutoModelForImageClassification as M
    return standard_loader(T, M, modelname, **kwargs)


@model_spec(
    model_type=ModelType.IMAGE_EVAL,
    mode=ModelMode.EVAL,
    output_fields=[],
    loader=load_image_eval,
    request_model=EvalImageRequest,
    response_model=EvalResponse,
    route="/eval/image",
)
class ImageEvalModel(BaseModelHandler):

    def __init__(self, modelname: str):
        super().__init__(modelname)

    def _run(
        self, user_id: str, message_id: str, request: EvalImageRequest
    ) -> EvalResponse:
        T = clock()

        try:
            image = decode_image(request.input)
        except Exception as e:
            logger.error(
                "[%s/%s] failed to decode image [%s]", user_id, message_id, str(e)
            )
            raise ValueError("invalid image input") from e

        logger.info(
            "[%s/%s] evaluating image %s",
            user_id, message_id, str(image.size),
        )

        inputs = self.processor(images=image, return_tensors="pt")

        T1 = clock()
        with torch.no_grad():
            outputs = self.model(**inputs)
        iduration = clock() - T1

        probs = torch.softmax(outputs.logits, dim=-1)[0]
        scores = [
            EvalScore(
                label=self.model.config.id2label[i],
                score=round(probs[i].item(), 4),
            )
            for i in range(len(probs))
        ]

        duration = clock() - T

        logger.info(
            "[%s/%s] '%s' scores=%s in %.2fs (inference %.2fs)",
            user_id, message_id, self.modelname,
            str(scores), duration, iduration,
        )

        usage = record_usage(
            user_id=user_id,
            model_type=ModelType.IMAGE_EVAL,
            modelname=self.modelname,
            duration=duration,
            inference=iduration,
        )

        return EvalResponse(model=self.modelname, scores=scores, usage=usage)
