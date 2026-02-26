"""process a sentence to an embedding"""

import json
import logging
import os
from time import perf_counter as clock

import torch
from api.models import (EmbeddingQuantization, EmbedTextRequest,
                        EmbedTextResponse, ModelType, ModelUsageStats)
from api.sqs_worker import SQSWorker
from sentence_transformers.quantization import quantize_embeddings
from shared import (get_memory_usage, get_userid_from_event,
                    lambda_event_to_data, mk_resp, update_metrics)

LOAD_PACKAGE_T = clock()
from models.cache_model import load_text_embedding

LOAD_PACKAGE_T = clock() - LOAD_PACKAGE_T


logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

logger.info("import load_text_embedding in %0.2fs", LOAD_PACKAGE_T)


MODELNAME = os.environ["MODELNAME"]


class TextEmbeddingModel:
    def __init__(self, modelname: str):
        self.modelname = modelname
        self.tokenizer, self.model = load_text_embedding(modelname)

    def embed(self, request: EmbedTextRequest) -> dict:
        if request.model != self.modelname:
            raise ValueError(
                f"model mismatch: expected {self.modelname}, got {request.model}"
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

        usage = ModelUsageStats(
            duration=duration,
            inference=inference_time,
            input_tokens=input_tokens,
            output_tokens=0,
            memory_usage=get_memory_usage(),
        )

        update_metrics(
            None, ModelType.TEXT_EMBEDDING, self.modelname, usage.model_dump()
        )

        response = EmbedTextResponse(
            model=self.modelname, embedding=vector, usage=usage
        )

        return mk_resp(200, response)


class EmbedSQSWorker(SQSWorker):
    def handle_message(self, msg):
        payload = json.loads(msg["Body"])
        user_id = payload["userid"]
        message_id = payload["message_id"]
        request = EmbedTextRequest.model_validate(payload["request"])

        try:
            return user_id, message_id, self.model.embed(request).model_dump()
        except Exception as e:
            logger.exception("embed failed for '%s'", str(request.model_dump()))
            return user_id, message_id, mk_resp(500, {"status": "error", "message": "embedding failed"})


def sqs_handler():
    modelname = os.environ["MODELNAME"]
    queue_url = os.environ["AWS_SQS_MODEL_QUEUE"]
    model = TextEmbeddingModel(modelname)
    worker = EmbedSQSWorker(queue_url, model)
    worker.run()
