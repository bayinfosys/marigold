"""Embedding submission routes."""

from fastapi import Request, Security, APIRouter

from api.models import EmbedImageRequest, EmbedTextRequest, SubmissionResponse
from api.routes._submit import _submit
from api.auth import apikey_auth
from shared.enums import ModelType


router = APIRouter()


@router.post(
    "/embed/text",
    description="embed text into a feature vector",
    response_model=SubmissionResponse,
)
async def embed_text(request: Request, body: EmbedTextRequest, user=Security(apikey_auth)):
    return await _submit(request, user.id, body.model_dump(), ModelType.TEXT_EMBEDDING)


@router.post(
    "/embed/image",
    description="embed an image into a feature vector",
    response_model=SubmissionResponse,
)
async def embed_image(request: Request, body: EmbedImageRequest, user=Security(apikey_auth)):
    return await _submit(request, user.id, body.model_dump(), ModelType.IMAGE_EMBEDDING)
