"""Text similarity evaluation.

Encodes two texts into the same embedding space and returns their cosine
similarity as a score in [-1.0, 1.0]. Values close to 1.0 indicate high
semantic similarity.

Reuses the sentence-transformers loading path from text_embed, since the
task is a comparison operation over the same embedding space.

Compatible models:
    sentence-transformers/all-MiniLM-L6-v2
    sentence-transformers/paraphrase-multilingual-mpnet-base-v2
"""

import logging
import os
from time import perf_counter as clock

import torch
import torch.nn.functional as F

from shared.enums import ModelMode, ModelType
from shared.registry import BaseModelHandler, model_spec
from shared.usage import record_usage
from models.text_embed import load_text_embedding
from api.models import EvalResponse, TextSimilarityRequest

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)


@model_spec(
    model_type=ModelType.TEXT_SIMILARITY,
    mode=ModelMode.EVAL,
    output_fields=[],
    loader=load_text_embedding,
    request_model=TextSimilarityRequest,
    response_model=EvalResponse,
    route="/eval/text-similarity",
)
class TextSimilarityModel(BaseModelHandler):

    def __init__(self, modelname: str):
        super().__init__(modelname)

    def _run(
        self, user_id: str, message_id: str, request: TextSimilarityRequest
    ) -> EvalResponse:
        T = clock()

        encoded = self.processor(
            [request.text1, request.text2],
            padding=True,
            truncation=True,
            return_tensors="pt",
        )
        input_tokens = encoded.input_ids.nelement()

        T1 = clock()
        embeddings = self.model.encode([request.text1, request.text2])
        iduration = clock() - T1

        t = torch.tensor(embeddings)
        similarity = round(
            F.cosine_similarity(t[0].unsqueeze(0), t[1].unsqueeze(0)).item(), 4
        )

        duration = clock() - T

        logger.info(
            "[%s/%s] '%s' similarity=%0.4f in %0.2fs (inference %0.2fs)",
            user_id,
            message_id,
            self.modelname,
            similarity,
            duration,
            iduration,
        )

        usage = record_usage(
            user_id=user_id,
            model_type=ModelType.TEXT_SIMILARITY,
            modelname=self.modelname,
            duration=duration,
            inference=iduration,
            input_tokens=input_tokens,
        )

        return EvalResponse(
            model=self.modelname,
            scores={"similarity": similarity},
            usage=usage,
        )
