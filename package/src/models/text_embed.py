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
from api.models import (EmbeddingQuantization, EmbeddingResponse,
                        EmbedTextRequest)
from models.standard_loader import ModelLoaderResult
from sentence_transformers.quantization import quantize_embeddings
from shared.enums import ModelMode, ModelType
from shared.registry import BaseModelHandler, model_spec
from shared.usage import record_usage

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

EmbedTextResponse = EmbeddingResponse


def load_text_embedding(modelname: str, cache_dir: str = None, **kwargs) -> ModelLoaderResult:
    """Text-to-vector embedding via sentence-transformers.

    The SentenceTransformer handles pooling internally. The tokenizer is
    loaded separately and stored as processor for token-counting only.
    """
    from sentence_transformers import SentenceTransformer as ST
    from transformers import AutoTokenizer

    st_kwargs = {}
    if cache_dir:
        st_kwargs["model_kwargs"] = {"cache_dir": cache_dir}
        st_kwargs["tokenizer_kwargs"] = {"cache_dir": cache_dir}

    model = ST(modelname, cache_folder=cache_dir, **st_kwargs)

    tokenizer = AutoTokenizer.from_pretrained(
        modelname,
        cache_dir=cache_dir,
    )

    return ModelLoaderResult(processor=tokenizer, model=model)


@model_spec(
    model_type=ModelType.TEXT_EMBEDDING,
    mode=ModelMode.EMBED,
    output_fields=[],
    loader=load_text_embedding,
    request_model=EmbedTextRequest,
    response_model=EmbeddingResponse,
    route="/embed/text",
)
class TextEmbeddingModel(BaseModelHandler):

    def __init__(self, modelname: str):
        super().__init__(modelname)

    def _run(
        self, user_id: str, message_id: str, request: EmbedTextRequest
    ) -> EmbeddingResponse:
        if request.model != self.modelname:
            raise ValueError(
                "model mismatch: expected %s, got %s" % (self.modelname, request.model)
            )
        if not isinstance(request.input, str):
            raise TypeError("request.input must be a string")

        T = clock()
        encoded = self.processor(
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
            user_id=user_id,
            model_type=ModelType.TEXT_EMBEDDING,
            modelname=self.modelname,
            duration=duration,
            inference=inference_time,
            input_tokens=input_tokens,
            load_time_ms=self.load_time_ms,
            model_size_bytes=self.model_size_bytes,
        )

        return EmbeddingResponse(
            model=self.modelname,
            embedding=vector,
            usage=usage,
        )
