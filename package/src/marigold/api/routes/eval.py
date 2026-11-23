"""Evaluation submission routes."""

from fastapi import Request, Security, APIRouter

from marigold.shared.schemas import (
    EvalImageRequest,
    EvalTextRequest,
    ImageTextEvalRequest,
    SubmissionResponse,
    TextSimilarityRequest,
)
from marigold.api.routes._submit import _submit
from marigold.api.auth import apikey_auth
from marigold.shared.enums import ModelType, ModelMode

router = APIRouter()


@router.post(
    "/eval/text",
    description="score a text against model-specific metrics",
    response_model=SubmissionResponse,
)
async def eval_text(request: Request, body: EvalTextRequest, user=Security(apikey_auth)):
    return await _submit(request, user.id, body.model_dump(), ModelType.TEXT_EVAL, ModelMode.EVAL)


@router.post(
    "/eval/text-similarity",
    description="score the semantic similarity between two texts",
    response_model=SubmissionResponse,
)
async def eval_text_similarity(request: Request, body: TextSimilarityRequest, user=Security(apikey_auth)):
    return await _submit(request, user.id, body.model_dump(), ModelType.TEXT_SIMILARITY, ModelMode.EVAL)


@router.post(
    "/eval/image",
    description="score an image against model-specific metrics",
    response_model=SubmissionResponse,
)
async def eval_image(request: Request, body: EvalImageRequest, user=Security(apikey_auth)):
    return await _submit(request, user.id, body.model_dump(), ModelType.IMAGE_EVAL, ModelMode.EVAL)


@router.post(
    "/eval/image-text",
    description="score the alignment between an image and a text description",
    response_model=SubmissionResponse,
)
async def eval_image_text(request: Request, body: ImageTextEvalRequest, user=Security(apikey_auth)):
    return await _submit(request, user.id, body.model_dump(), ModelType.IMAGE_SIMILARITY, ModelMode.EVAL)
