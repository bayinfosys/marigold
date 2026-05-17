"""Image-text alignment evaluation.

Encodes an image and a text string into a shared CLIP embedding space and
returns their cosine similarity as a single EvalScore with label 'alignment'.
Values close to 1.0 indicate strong alignment between the image content and
the text description.

Reuses the sentence-transformers loading path from image_embed, since
CLIP-compatible models are already handled there.

Compatible models:
    clip-ViT-B-32 (openai/clip-vit-base-patch32)
    clip-ViT-L-14
"""

import logging
import os
from time import perf_counter as clock

import torch
import torch.nn.functional as F
from api.models import EvalResponse, EvalScore, ImageTextEvalRequest
from models.image_embed import load_image_embedding
from shared.enums import ModelMode, ModelType
from shared.outputs import decode_image
from shared.registry import BaseModelHandler, model_spec
from shared.usage import record_usage

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)


@model_spec(
    model_type=ModelType.IMAGE_TEXT_EVAL,
    mode=ModelMode.EVAL,
    output_fields=[],
    loader=load_image_embedding,
    request_model=ImageTextEvalRequest,
    response_model=EvalResponse,
    route="/eval/image-text",
)
class ImageTextEvalModel(BaseModelHandler):

    def __init__(self, modelname: str):
        super().__init__(modelname)

    def _run(
        self, user_id: str, message_id: str, request: ImageTextEvalRequest
    ) -> EvalResponse:
        T = clock()

        try:
            image = decode_image(request.image)
        except Exception as e:
            logger.error(
                "[%s/%s] failed to decode image [%s]", user_id, message_id, str(e)
            )
            raise ValueError("invalid image input") from e

        T1 = clock()
        image_emb = self.model.encode(image)
        text_emb = self.model.encode(request.text)
        iduration = clock() - T1

        ti = torch.tensor(image_emb).unsqueeze(0)
        tt = torch.tensor(text_emb).unsqueeze(0)
        alignment = round(F.cosine_similarity(ti, tt).item(), 4)

        duration = clock() - T

        logger.info(
            "[%s/%s] '%s' alignment=%.4f in %.2fs (inference %.2fs)",
            user_id, message_id, self.modelname,
            alignment, duration, iduration,
        )

        usage = record_usage(
            user_id=user_id,
            model_type=ModelType.IMAGE_TEXT_EVAL,
            modelname=self.modelname,
            duration=duration,
            inference=iduration,
            load_time_ms=self.load_time_ms,
            model_size_bytes=self.model_size_bytes,
        )

        return EvalResponse(
            model=self.modelname,
            scores=[EvalScore(label="alignment", score=alignment)],
            usage=usage,
        )
