"""Embedding submission routes."""

from fastapi import Request, Security
from fastapi_aws import APIKeyAuthorizer, AWSAPIRouter

from api.models import EmbedImageRequest, EmbedTextRequest, SubmissionResponse
from api.routes._submit import _submit
from api.auth import apikey_auth


router = AWSAPIRouter()

_LAMBDA = "${request_receiver_lambda_arn}"
_IAM = "${request_receiver_lambda_iam_role_arn}"


@router.post(
    "/embed/text",
    description="embed text into a feature vector",
    response_model=SubmissionResponse,
    aws_lambda_arn=_LAMBDA,
    aws_iam_arn=_IAM,
)
async def embed_text(request: Request, body: EmbedTextRequest, user=Security(apikey_auth)):
    return await _submit(request, user.id, body.model_dump())


@router.post(
    "/embed/image",
    description="embed an image into a feature vector",
    response_model=SubmissionResponse,
    aws_lambda_arn=_LAMBDA,
    aws_iam_arn=_IAM,
)
async def embed_image(request: Request, body: EmbedImageRequest, user=Security(apikey_auth)):
    return await _submit(request, user.id, body.model_dump())
