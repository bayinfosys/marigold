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

from shared.enums import ModelMode, ModelType
from shared.outputs import decode_image
from shared.registry import BaseModelHandler, model_spec
from shared.usage import record_usage
from models.standard_loader import ModelLoaderResult, standard_loader
from api.models import EmbedImageRequest, EmbeddingResponse

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)


def load_image_embedding(modelname: str, cache_dir: str = None, **kwargs) -> ModelLoaderResult:
    """Image-to-vector embedding.

    Uses sentence-transformers for CLIP-compatible models so that image and
    text embeddings share a vector space. For non-CLIP checkpoints falls back
    to AutoImageProcessor + AutoModel.

    processor is None in the sentence-transformers path; the SentenceTransformer
    handles tokenisation internally.
    """
    from sentence_transformers import SentenceTransformer as ST

    T0 = clock()
    try:
        model = ST(modelname, cache_folder=cache_dir)
        logger.info(
            "loaded '%s' as SentenceTransformer in %0.2fs", modelname, clock() - T0
        )
        return ModelLoaderResult(processor=None, model=model)
    except Exception:
        pass

    from transformers import AutoImageProcessor as P
    from transformers import AutoModel as M

    return standard_loader(P, M, modelname, cache_dir=cache_dir, **kwargs)


@model_spec(
    model_type=ModelType.IMAGE_EMBEDDING,
    mode=ModelMode.EMBED,
    output_fields=[],
    loader=load_image_embedding,
    request_model=EmbedImageRequest,
    response_model=EmbeddingResponse,
    route="/embed/image",
)
class ImageEmbeddingModel(BaseModelHandler):

    def __init__(self, modelname: str):
        super().__init__(modelname)
        self.precision = int(os.getenv("PRECISION", "3"))

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
                if hasattr(outputs, "image_embeds"):
                    embeddings = outputs.image_embeds.cpu()
                else:
                    embeddings = outputs.last_hidden_state[:, 0].cpu()

            raw = embeddings[0].tolist()

        iduration = clock() - T1

        if self.precision > 0:
            raw = [round(v, self.precision) for v in raw]

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
            user_id=user_id,
            model_type=ModelType.IMAGE_EMBEDDING,
            modelname=self.modelname,
            duration=duration,
            inference=iduration,
            input_tokens=input_tokens,
        )

        return EmbeddingResponse(
            model=self.modelname,
            embedding=raw,
            usage=usage,
        )
