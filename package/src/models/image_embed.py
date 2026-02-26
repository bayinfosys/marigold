"""Image embedding model.

Encodes an image into a fixed-size vector using a vision transformer.
Uses sentence-transformers for CLIP-compatible models so that image and
text embeddings share the same vector space and support cross-modal search.

Compatible models:
    clip-ViT-B-32 (openai/clip-vit-base-patch32)
    any AutoImageProcessor + AutoModel checkpoint
"""

import logging
import os
from time import perf_counter as clock

import torch
from api.models import EmbeddingResponse, EmbedImageRequest, ModelType
from models import BaseModelHandler
from models.cache_model import load_image_embedding
from shared import decode_image, record_usage

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

CACHE_DIR = os.getenv("CACHE_DIR", "/mnt/shared/models")
PRECISION = int(os.getenv("PRECISION", "3"))


class ImageEmbeddingModel(BaseModelHandler):

    def __init__(self, modelname: str):
        super().__init__(modelname)
        _T = clock()
        # load_image_embedding returns (processor, model) for standard
        # transformers checkpoints. For sentence-transformers CLIP models the
        # processor is None and the model is a SentenceTransformer instance.
        self.processor, self.model = load_image_embedding(
            modelname, cache_dir=CACHE_DIR
        )
        logger.info("'%s' loaded in %0.2fs", modelname, clock() - _T)

    def process(
        self, user_id: str, message_id: str, request: dict
    ) -> EmbeddingResponse:
        req = EmbedImageRequest.model_validate(request)
        return self._run(user_id, message_id, req)

    def _run(
        self, user_id: str, message_id: str, request: EmbedImageRequest
    ) -> EmbeddingResponse:
        T = clock()

        try:
            image = decode_image(request.input)
        except Exception as e:
            logger.error(
                "[%s/%s] failed to decode image [%s]", user_id, message_id, str(e)
            )
            raise ValueError("invalid image input") from e

        logger.info(
            "[%s/%s] embedding image %s mode=%s",
            user_id,
            message_id,
            str(image.size),
            image.mode,
        )

        T1 = clock()

        if self.processor is None:
            # sentence-transformers SentenceTransformer path (CLIP-style)
            embeddings = self.model.encode(image)
            raw = (
                embeddings.tolist()
                if hasattr(embeddings, "tolist")
                else list(embeddings)
            )
            input_tokens = 0
        else:
            # standard transformers AutoModel path
            inputs = self.processor(images=image, return_tensors="pt")
            input_tokens = inputs.get("input_ids", torch.tensor([])).nelement()

            with torch.no_grad():
                outputs = self.model(**inputs)
                # CLS token embedding from the last hidden state
                embeddings = outputs.last_hidden_state[:, 0].cpu()

            raw = embeddings[0].tolist()

        iduration = clock() - T1

        if PRECISION > 0:
            raw = [round(v, PRECISION) for v in raw]

        # quantization is requested but not applied here because
        # sentence_transformers.quantize_embeddings requires numpy arrays
        # and the quantization path depends on the vector format; apply at
        # the caller's discretion if needed.
        # TODO: apply quantize_embeddings when request.quantization != FLOAT32

        duration = clock() - T

        logger.info(
            "[%s/%s] '%s' %i-dim embedding in %0.2fs (inference %0.2fs)",
            user_id,
            message_id,
            self.modelname,
            len(raw),
            duration,
            iduration,
        )

        usage = record_usage(
            user_id,
            ModelType.IMAGE_EMBEDDING,
            self.modelname,
            duration,
            iduration,
            input_tokens,
        )

        return EmbeddingResponse(
            model=self.modelname,
            embedding=raw,
            usage=usage,
        )
