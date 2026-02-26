from fastapi import Security
from fastapi_aws import APIKeyAuthorizer, AWSAPIRouter

from .models import (DeleteCacheResponse, DepthRequest, EmbedImageRequest,
                     EmbedTextRequest, Img2MaskRequest, Img2TxtRequest,
                     InstructRequest, PollResponse, SubmissionResponse,
                     TTSRequest, Txt2ImgRequest, UsageResponse)

apikey_auth = APIKeyAuthorizer(authorizer_name="${apikey_authorizer_name}")

# cognito_auth = CognitoAuthorizer(
#     authorizer_name="${cognito_authorizer_name}"
# )
cognito_auth = None

router = AWSAPIRouter()


#
# Embedding
#
# Embed routes use two-level paths (/embed/text, /embed/image) and cannot
# share the generic /{model_type}/{message_id} polling routes below.
# All six routes are registered explicitly.
#
@router.post(
    "/embed/text",
    description="embed text into a feature space",
    response_model=SubmissionResponse,
    aws_lambda_arn="${polling_start_lambda_arn}",
    aws_iam_arn="${polling_start_lambda_iam_role_arn}",
    tags=["models", "embedding"],
)
async def embed_text(body: EmbedTextRequest, user=Security(apikey_auth)):
    return SubmissionResponse()


@router.get(
    "/embed/text/{message_id}",
    description="poll for a previously submitted text embedding",
    response_model=PollResponse,
    aws_lambda_arn="${polling_start_lambda_arn}",
    aws_iam_arn="${polling_start_lambda_iam_role_arn}",
    tags=["models", "embedding"],
)
async def poll_embed_text(user=Security(apikey_auth)):
    return


@router.delete(
    "/embed/text/{message_id}",
    description="delete a cached text embedding result",
    response_model=DeleteCacheResponse,
    aws_lambda_arn="${polling_start_lambda_arn}",
    aws_iam_arn="${polling_start_lambda_iam_role_arn}",
    tags=["models", "embedding"],
)
async def delete_embed_text(user=Security(apikey_auth)):
    return


@router.post(
    "/embed/image",
    description="embed an image into a feature space",
    response_model=SubmissionResponse,
    aws_lambda_arn="${polling_start_lambda_arn}",
    aws_iam_arn="${polling_start_lambda_iam_role_arn}",
    tags=["models", "embedding"],
)
async def embed_image(body: EmbedImageRequest, user=Security(apikey_auth)):
    return SubmissionResponse()


@router.get(
    "/embed/image/{message_id}",
    description="poll for a previously submitted image embedding",
    response_model=PollResponse,
    aws_lambda_arn="${polling_start_lambda_arn}",
    aws_iam_arn="${polling_start_lambda_iam_role_arn}",
    tags=["models", "embedding"],
)
async def poll_embed_image(user=Security(apikey_auth)):
    return


@router.delete(
    "/embed/image/{message_id}",
    description="delete a cached image embedding result",
    response_model=DeleteCacheResponse,
    aws_lambda_arn="${polling_start_lambda_arn}",
    aws_iam_arn="${polling_start_lambda_iam_role_arn}",
    tags=["models", "embedding"],
)
async def delete_embed_image(user=Security(apikey_auth)):
    return


#
# Instruct
#
@router.post(
    "/instruct",
    description="submit a chat or instruction request",
    response_model=SubmissionResponse,
    aws_lambda_arn="${polling_start_lambda_arn}",
    aws_iam_arn="${polling_start_lambda_iam_role_arn}",
    tags=["models", "instruct"],
)
async def instruct(body: InstructRequest, user=Security(apikey_auth)):
    return SubmissionResponse()


#
# Text-to-speech
#
@router.post(
    "/tts",
    description="submit a text-to-speech request",
    response_model=SubmissionResponse,
    aws_lambda_arn="${polling_start_lambda_arn}",
    aws_iam_arn="${polling_start_lambda_iam_role_arn}",
    tags=["models", "tts"],
)
async def tts(body: TTSRequest, user=Security(apikey_auth)):
    return SubmissionResponse()


#
# Image generation (txt2img)
#
@router.post(
    "/txt2img",
    description="submit a text-to-image generation request",
    response_model=SubmissionResponse,
    aws_lambda_arn="${polling_start_lambda_arn}",
    aws_iam_arn="${polling_start_lambda_iam_role_arn}",
    tags=["models", "image"],
)
async def txt2img(body: Txt2ImgRequest, user=Security(apikey_auth)):
    return SubmissionResponse()


#
# Image to text (img2txt)
#
@router.post(
    "/img2txt",
    description="submit an image captioning or visual question answering request",
    response_model=SubmissionResponse,
    aws_lambda_arn="${polling_start_lambda_arn}",
    aws_iam_arn="${polling_start_lambda_iam_role_arn}",
    tags=["models", "image"],
)
async def img2txt(body: Img2TxtRequest, user=Security(apikey_auth)):
    return SubmissionResponse()


#
# Depth estimation
#
@router.post(
    "/depth",
    description="submit a monocular depth estimation request",
    response_model=SubmissionResponse,
    aws_lambda_arn="${polling_start_lambda_arn}",
    aws_iam_arn="${polling_start_lambda_iam_role_arn}",
    tags=["models", "image"],
)
async def depth(body: DepthRequest, user=Security(apikey_auth)):
    return SubmissionResponse()


#
# Image segmentation (img2mask)
#
@router.post(
    "/img2mask",
    description="submit an image segmentation request",
    response_model=SubmissionResponse,
    aws_lambda_arn="${polling_start_lambda_arn}",
    aws_iam_arn="${polling_start_lambda_iam_role_arn}",
    tags=["models", "image"],
)
async def img2mask(body: Img2MaskRequest, user=Security(apikey_auth)):
    return SubmissionResponse()


#
# Generic polling routes
#
# Covers all single-segment model type paths: instruct, tts, txt2img, img2txt,
# depth, img2mask.  Embed routes are registered above because their paths are
# two segments deep (/embed/text, /embed/image).
#
# The result field type in PollResponse varies by model type.  The OpenAPI
# spec cannot express this without a union; clients should refer to the
# per-type POST schema to interpret the result payload.
#
@router.get(
    "/{model_type}/{message_id}",
    description="poll for the status and result of a submitted job",
    response_model=PollResponse,
    aws_lambda_arn="${polling_start_lambda_arn}",
    aws_iam_arn="${polling_start_lambda_iam_role_arn}",
    tags=["polling"],
)
async def poll_result(user=Security(apikey_auth)):
    return


@router.delete(
    "/{model_type}/{message_id}",
    description="delete a cached job result",
    response_model=DeleteCacheResponse,
    aws_lambda_arn="${polling_start_lambda_arn}",
    aws_iam_arn="${polling_start_lambda_iam_role_arn}",
    tags=["polling"],
)
async def delete_result(user=Security(apikey_auth)):
    return


#
# Binary output retrieval
#
# All binary-output model types write to S3 under the key schema:
#   outputs/{model_type}/{message_id}/{field_name}
#
# The generic route covers all model types and output field names.
# Convenience routes follow for the common single-output cases so clients
# do not need to inspect the polling response to construct the path.
#
@router.get(
    "/output/{model_type}/{message_id}/{field_name}",
    description="retrieve a named binary output for a completed job",
    aws_s3_bucket="${s3_output_bucket_name}",
    aws_s3_object_key="outputs/{model_type}/{message_id}/{field_name}",
    aws_iam_arn="${s3_read_output_iam_role_arn}",
    tags=["output"],
)
async def get_output(user=Security(apikey_auth)):
    return


#
# Usage
#
@router.get(
    "/usage/{key}/{period}",
    response_model=UsageResponse,
    aws_lambda_arn="${usage_stats_lambda_arn}",
    aws_iam_arn="${usage_stats_lambda_iam_role_arn}",
    tags=["usage"],
)
async def usage_stats(user=Security(apikey_auth)):
    return


#
# API spec
#
@router.get(
    "/openapi.json",
    aws_s3_bucket="${s3_assets_bucket_name}",
    aws_s3_object_key="openapi.json",
    aws_iam_arn="${s3_read_api_object_iam_role_arn}",
    tags=["api"],
)
async def openapi_spec(user=Security(apikey_auth)):
    return


@router.get(
    "/models.json",
    aws_s3_bucket="${s3_assets_bucket_name}",
    aws_s3_object_key="public_models_reference.json",
    aws_iam_arn="${s3_read_api_object_iam_role_arn}",
    tags=["api"],
)
async def model_list(user=Security(apikey_auth)):
    return


#
# API key management
#
@router.post(
    "/users/keys",
    description="create an API key for programmatic access",
    aws_lambda_arn="${key_management_lambda_arn}",
    aws_iam_arn="${key_management_lambda_iam_role_arn}",
    tags=["keys"],
)
async def create_api_key(user=Security(cognito_auth)):
    return


@router.get(
    "/users/keys",
    description="list API keys for the current user",
    aws_lambda_arn="${key_management_lambda_arn}",
    aws_iam_arn="${key_management_lambda_iam_role_arn}",
    tags=["keys"],
)
async def list_api_keys(user=Security(cognito_auth)):
    return


@router.delete(
    "/users/keys/{key_id}",
    description="delete an API key",
    aws_lambda_arn="${key_management_lambda_arn}",
    aws_iam_arn="${key_management_lambda_iam_role_arn}",
    tags=["keys"],
)
async def delete_api_key(user=Security(cognito_auth)):
    return
