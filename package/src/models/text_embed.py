"""Text embedding models.

Encodes a text string into a fixed-size vector.

Compatible models:
    sentence-transformers/paraphrase-multilingual-mpnet-base-v2
    sentence-transformers/all-MiniLM-L6-v2
"""

import logging
import os
from time import perf_counter as clock

import torch
from api.models import (EmbeddingQuantization, EmbedTextRequest,
                        EmbedTextResponse, ModelType)
from models import BaseModelHandler
from models.cache_model import load_text_embedding
from sentence_transformers.quantization import quantize_embeddings
from shared import record_usage

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)


class TextEmbeddingModel(BaseModelHandler):

    def __init__(self, modelname: str):
        super().__init__(modelname)
        _T = clock()
        self.tokenizer, self.model = load_text_embedding(modelname)
        logger.info("'%s' loaded in %0.2fs", modelname, clock() - _T)

    def process(
        self, user_id: str, message_id: str, request: dict
    ) -> EmbedTextResponse:
        req = EmbedTextRequest.model_validate(request)
        return self._run(user_id, message_id, req)

    def _run(
        self, user_id: str, message_id: str, request: EmbedTextRequest
    ) -> EmbedTextResponse:
        if request.model != self.modelname:
            raise ValueError(
                "model mismatch: expected %s, got %s" % (self.modelname, request.model)
            )
        if not isinstance(request.input, str):
            raise TypeError("request.input must be a string")

        T = clock()
        encoded = self.tokenizer(
            [request.input], padding=True, truncation=True, return_tensors="pt"
        )
        input_tokens = encoded.input_ids.nelement()

        with torch.no_grad():
            embeddings = self.model.encode(request.input)

        inference_time = clock() - T

        if request.quantization != EmbeddingQuantization.FLOAT32:
            embeddings = quantize_embeddings(embeddings, precision=request.quantization)

        vector = embeddings.tolist()
        duration = clock() - T

        logger.info(
            "[%s/%s] '%s' %i-dim embedding in %0.2fs (inference %0.2fs)",
            user_id,
            message_id,
            self.modelname,
            len(vector),
            duration,
            inference_time,
        )

        usage = record_usage(
            user_id,
            ModelType.TEXT_EMBEDDING,
            self.modelname,
            duration,
            inference_time,
            input_tokens=input_tokens,
        )

        return EmbedTextResponse(
            model=self.modelname,
            embedding=vector,
            usage=usage,
        )
