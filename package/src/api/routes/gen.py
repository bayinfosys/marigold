"""Generation submission routes."""

from fastapi import Request, Security, APIRouter

from api.models import (
    DepthRequest,
    Img2MaskRequest,
    Img2TxtRequest,
    InstructRequest,
    SubmissionResponse,
    TTSRequest,
    Txt2AudioRequest,
    Txt2ImgRequest,
)
from api.routes._submit import _submit
from api.auth import apikey_auth
from shared.enums import ModelType

router = APIRouter()


@router.post(
    "/gen/instruct",
    description="submit a chat or instruction-following request",
    response_model=SubmissionResponse,
)
async def gen_instruct(request: Request, body: InstructRequest, user=Security(apikey_auth)):
    return await _submit(request, user.id, body.model_dump(), ModelType.INSTRUCT)


@router.post(
    "/gen/tts",
    description="submit a text-to-speech synthesis request",
    response_model=SubmissionResponse,
)
async def gen_tts(request: Request, body: TTSRequest, user=Security(apikey_auth)):
    return await _submit(request, user.id, body.model_dump(), ModelType.TTS)


@router.post(
    "/gen/txt2audio",
    description="submit a text-to-audio generation request (music or sound effects)",
    response_model=SubmissionResponse,
)
async def gen_txt2audio(request: Request, body: Txt2AudioRequest, user=Security(apikey_auth)):
    return await _submit(request, user.id, body.model_dump(), ModelType.TXT2AUDIO)


@router.post(
    "/gen/txt2img",
    description="submit a text-to-image generation request",
    response_model=SubmissionResponse,
)
async def gen_txt2img(request: Request, body: Txt2ImgRequest, user=Security(apikey_auth)):
    return await _submit(request, user.id, body.model_dump(), ModelType.TXT2IMG)


@router.post(
    "/gen/img2txt",
    description="submit an image captioning or visual question answering request",
    response_model=SubmissionResponse,
)
async def gen_img2txt(request: Request, body: Img2TxtRequest, user=Security(apikey_auth)):
    return await _submit(request, user.id, body.model_dump(), ModelType.IMG2TXT)


@router.post(
    "/gen/depth",
    description="submit a monocular depth estimation request",
    response_model=SubmissionResponse,
)
async def gen_depth(request: Request, body: DepthRequest, user=Security(apikey_auth)):
    return await _submit(request, user.id, body.model_dump(), ModelType.DEPTH)


@router.post(
    "/gen/img2mask",
    description="submit an image segmentation request",
    response_model=SubmissionResponse,
)
async def gen_img2mask(request: Request, body: Img2MaskRequest, user=Security(apikey_auth)):
    return await _submit(request, user.id, body.model_dump(), ModelType.IMG2MASK)
