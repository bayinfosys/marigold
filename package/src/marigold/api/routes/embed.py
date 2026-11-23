"""Embedding submission routes."""

from fastapi import Request, Security, APIRouter

from marigold.shared.schemas import EmbedImageRequest, EmbedTextRequest, SubmissionResponse
from marigold.api.routes._submit import _submit
from marigold.api.auth import apikey_auth
from marigold.shared.enums import ModelType, ModelMode


router = APIRouter()


@router.post(
    "/embed/text",
    description="embed text into a feature vector",
    response_model=SubmissionResponse,
)
async def embed_text(request: Request, body: EmbedTextRequest, user=Security(apikey_auth)):
    return await _submit(request, user.id, body.model_dump(), ModelType.TEXT_EMBEDDING, ModelMode.EMBED)


@router.post(
    "/embed/image",
    description="embed an image into a feature vector",
    response_model=SubmissionResponse,
)
async def embed_image(request: Request, body: EmbedImageRequest, user=Security(apikey_auth)):
    return await _submit(request, user.id, body.model_dump(), ModelType.IMAGE_EMBEDDING, ModelMode.EMBED)
