"""API route definitions.

All submission paths are two segments deep:
    /embed/{task}
    /eval/{task}
    /gen/{task}

This allows poll and delete to be covered by two generic routes:
    GET    /{mode}/{task}/{message_id}
    DELETE /{mode}/{task}/{message_id}

Binary output retrieval uses a single generic route:
    GET    /output/{mode}/{task}/{message_id}/{field}

The S3 key schema matches: outputs/{model_type}/{message_id}/{field}
where model_type is the ModelType enum value for that task.
"""

from fastapi import Security
from fastapi_aws import APIKeyAuthorizer, AWSAPIRouter

from .models import (
    DeleteCacheResponse,
    DepthRequest,
    EmbedImageRequest,
    EmbedTextRequest,
    EmbeddingResponse,
    EvalImageRequest,
    EvalResponse,
    EvalTextRequest,
    ImageTextEvalRequest,
    Img2MaskRequest,
    Img2TxtRequest,
    InstructRequest,
    InstructResponse,
    PollResponse,
    SubmissionResponse,
    TextSimilarityRequest,
    TTSRequest,
    Txt2AudioRequest,
    Txt2ImgRequest,
    UsageResponse,
)

apikey_auth = APIKeyAuthorizer(authorizer_name="${apikey_authorizer_name}")

# cognito_auth = CognitoAuthorizer(
#     authorizer_name="${cognito_authorizer_name}"
# )
cognito_auth = None

router = AWSAPIRouter()


# ---------------------------------------------------------------------------
# Embed
# ---------------------------------------------------------------------------

@router.post(
    "/embed/text",
    description="embed text into a feature vector",
    response_model=SubmissionResponse,
    aws_lambda_arn="${polling_start_lambda_arn}",
    aws_iam_arn="${polling_start_lambda_iam_role_arn}",
    tags=["embed"],
)
async def embed_text(body: EmbedTextRequest, user=Security(apikey_auth)):
    return SubmissionResponse()


@router.post(
    "/embed/image",
    description="embed an image into a feature vector",
    response_model=SubmissionResponse,
    aws_lambda_arn="${polling_start_lambda_arn}",
    aws_iam_arn="${polling_start_lambda_iam_role_arn}",
    tags=["embed"],
)
async def embed_image(body: EmbedImageRequest, user=Security(apikey_auth)):
    return SubmissionResponse()


# ---------------------------------------------------------------------------
# Eval
# ---------------------------------------------------------------------------

@router.post(
    "/eval/text",
    description="score a text against model-specific metrics",
    response_model=SubmissionResponse,
    aws_lambda_arn="${polling_start_lambda_arn}",
    aws_iam_arn="${polling_start_lambda_iam_role_arn}",
    tags=["eval"],
)
async def eval_text(body: EvalTextRequest, user=Security(apikey_auth)):
    return SubmissionResponse()


@router.post(
    "/eval/text-similarity",
    description="score the semantic similarity between two texts",
    response_model=SubmissionResponse,
    aws_lambda_arn="${polling_start_lambda_arn}",
    aws_iam_arn="${polling_start_lambda_iam_role_arn}",
    tags=["eval"],
)
async def eval_text_similarity(body: TextSimilarityRequest, user=Security(apikey_auth)):
    return SubmissionResponse()


@router.post(
    "/eval/image",
    description="score an image against model-specific metrics",
    response_model=SubmissionResponse,
    aws_lambda_arn="${polling_start_lambda_arn}",
    aws_iam_arn="${polling_start_lambda_iam_role_arn}",
    tags=["eval"],
)
async def eval_image(body: EvalImageRequest, user=Security(apikey_auth)):
    return SubmissionResponse()


@router.post(
    "/eval/image-text",
    description="score the alignment between an image and a text description",
    response_model=SubmissionResponse,
    aws_lambda_arn="${polling_start_lambda_arn}",
    aws_iam_arn="${polling_start_lambda_iam_role_arn}",
    tags=["eval"],
)
async def eval_image_text(body: ImageTextEvalRequest, user=Security(apikey_auth)):
    return SubmissionResponse()


# ---------------------------------------------------------------------------
# Gen
# ---------------------------------------------------------------------------

@router.post(
    "/gen/instruct",
    description="submit a chat or instruction-following request",
    response_model=SubmissionResponse,
    aws_lambda_arn="${polling_start_lambda_arn}",
    aws_iam_arn="${polling_start_lambda_iam_role_arn}",
    tags=["gen"],
)
async def gen_instruct(body: InstructRequest, user=Security(apikey_auth)):
    return SubmissionResponse()


@router.post(
    "/gen/tts",
    description="submit a text-to-speech synthesis request",
    response_model=SubmissionResponse,
    aws_lambda_arn="${polling_start_lambda_arn}",
    aws_iam_arn="${polling_start_lambda_iam_role_arn}",
    tags=["gen"],
)
async def gen_tts(body: TTSRequest, user=Security(apikey_auth)):
    return SubmissionResponse()


@router.post(
    "/gen/txt2audio",
    description="submit a text-to-audio generation request (music or sound effects)",
    response_model=SubmissionResponse,
    aws_lambda_arn="${polling_start_lambda_arn}",
    aws_iam_arn="${polling_start_lambda_iam_role_arn}",
    tags=["gen"],
)
async def gen_txt2audio(body: Txt2AudioRequest, user=Security(apikey_auth)):
    return SubmissionResponse()


@router.post(
    "/gen/txt2img",
    description="submit a text-to-image generation request",
    response_model=SubmissionResponse,
    aws_lambda_arn="${polling_start_lambda_arn}",
    aws_iam_arn="${polling_start_lambda_iam_role_arn}",
    tags=["gen"],
)
async def gen_txt2img(body: Txt2ImgRequest, user=Security(apikey_auth)):
    return SubmissionResponse()


@router.post(
    "/gen/img2txt",
    description="submit an image captioning or visual question answering request",
    response_model=SubmissionResponse,
    aws_lambda_arn="${polling_start_lambda_arn}",
    aws_iam_arn="${polling_start_lambda_iam_role_arn}",
    tags=["gen"],
)
async def gen_img2txt(body: Img2TxtRequest, user=Security(apikey_auth)):
    return SubmissionResponse()


@router.post(
    "/gen/depth",
    description="submit a monocular depth estimation request",
    response_model=SubmissionResponse,
    aws_lambda_arn="${polling_start_lambda_arn}",
    aws_iam_arn="${polling_start_lambda_iam_role_arn}",
    tags=["gen"],
)
async def gen_depth(body: DepthRequest, user=Security(apikey_auth)):
    return SubmissionResponse()


@router.post(
    "/gen/img2mask",
    description="submit an image segmentation request",
    response_model=SubmissionResponse,
    aws_lambda_arn="${polling_start_lambda_arn}",
    aws_iam_arn="${polling_start_lambda_iam_role_arn}",
    tags=["gen"],
)
async def gen_img2mask(body: Img2MaskRequest, user=Security(apikey_auth)):
    return SubmissionResponse()


# ---------------------------------------------------------------------------
# Polling and deletion
#
# Two generic routes cover all submission paths. {mode} is one of embed,
# eval, gen. {task} is the task name within that mode (e.g. text, tts,
# img2mask). The polling lambda looks up the result by message_id regardless
# of the mode/task path parameters.
# ---------------------------------------------------------------------------

@router.get(
    "/{mode}/{task}/{message_id}",
    description="poll for the status and result of a submitted job",
    response_model=PollResponse,
    aws_lambda_arn="${polling_start_lambda_arn}",
    aws_iam_arn="${polling_start_lambda_iam_role_arn}",
    tags=["polling"],
)
async def poll_result(user=Security(apikey_auth)):
    return


@router.delete(
    "/{mode}/{task}/{message_id}",
    description="delete a cached job result",
    response_model=DeleteCacheResponse,
    aws_lambda_arn="${polling_start_lambda_arn}",
    aws_iam_arn="${polling_start_lambda_iam_role_arn}",
    tags=["polling"],
)
async def delete_result(user=Security(apikey_auth)):
    return


# ---------------------------------------------------------------------------
# Binary output retrieval
#
# Binary outputs are written to S3 under:
#   outputs/{model_type}/{message_id}/{field}
#
# {mode} and {task} in the path identify which model_type to resolve.
# {field} is the output field name declared in the handler's ModelSpec
# output_fields list (e.g. audio, image, depth, mask).
# ---------------------------------------------------------------------------

@router.get(
    "/output/{mode}/{task}/{message_id}/{field}",
    description="retrieve a named binary output for a completed job",
    aws_s3_bucket="${s3_output_bucket_name}",
    aws_s3_object_key="outputs/{mode}-{task}/{message_id}/{field}",
    aws_iam_arn="${s3_read_output_iam_role_arn}",
    tags=["output"],
)
async def get_output(user=Security(apikey_auth)):
    return


# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------

@router.get(
    "/usage/{key}/{period}",
    response_model=UsageResponse,
    aws_lambda_arn="${usage_stats_lambda_arn}",
    aws_iam_arn="${usage_stats_lambda_iam_role_arn}",
    tags=["usage"],
)
async def usage_stats(user=Security(apikey_auth)):
    return


# ---------------------------------------------------------------------------
# API spec and model catalogue
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# API key management
# ---------------------------------------------------------------------------

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
