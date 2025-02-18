from fastapi import Security

from fastapi_aws import AWSAPIRouter, LambdaAuthorizer

from .models import EmbedTextRequest, EmbedImageRequest, EmbeddingsResponse
from .models import InstructRequest, InstructResponse
from .models import TTSRequest, TTSResponse
from .models import UsageResponse


lambda_auth = LambdaAuthorizer(
    authorizer_name="${lambda_authorizer_name}",
    aws_lambda_uri="${lambda_authorizer_uri}",
    aws_iam_role_arn="${lambda_authorizer_iam_role_arn}",
)

router = AWSAPIRouter()


#
# model descriptions
#
# @router.get(
#    "/models",
#    response_model=ListModelsResponse,
#    aws_sfn_sync_arn="${models_definition_arn}", # FIXME: this is an s3 arn
#    aws_iam_arn="${models_definition_iam_role_arn}",
#    tags=["models"],
# )
# async def list_models():
#    return ListModelsResponse()


#
# embedding models
#
@router.post(
    "/embed/text",
    description="embed text into a feature space",
    response_model=EmbeddingsResponse,
    aws_lambda_uri="${polling_start_lambda_arn}",
    aws_iam_arn="${polling_start_lambda_iam_role_arn}",
    tags=["models", "embedding"],
)
async def embed_text(body: EmbedTextRequest, user=Security(lambda_auth)):
    return EmbeddingsResponse()


@router.get(
    "/embed/text/{message_id}",
    description="retrieve previously computed embeddings",
    response_model=EmbeddingsResponse,
    aws_lambda_uri="${polling_start_lambda_arn}",
    aws_iam_arn="${polling_start_lambda_iam_role_arn}",
    tags=["models", "embedding"],
)
async def fetch_embed_text(user=Security(lambda_auth)):
    return EmbeddingsResponse()


# @router.post(
#    "/embed/text/direct",
#    description="call the embed text model directly, with no polling buffer.",
#    response_model=EmbeddingsResponse,
#    aws_lambda_uri="${text_embedding_lambda_function_arn}",
#    aws_iam_arn="${text_embedding_invoke_lambda_iam_role_arn}",
#    tags=["models", "embedding"],
# )
# async def embed_text(body: EmbedTextRequest, user=Security(lambda_auth)):
#    return EmbeddingsResponse()


@router.post(
    "/embed/image",
    response_model=EmbeddingsResponse,
    aws_sfn_sync_arn="${image_embedding_step_function_arn}",
    aws_iam_arn="${image_embedding_step_function_iam_role_arn}",
    tags=["models", "embedding"],
)
async def embed_image(body: EmbedImageRequest, user=Security(lambda_auth)):
    return EmbeddingsResponse()


#
# instruct
#
@router.post(
    "/instruct",
    response_model=InstructResponse,
    aws_lambda_uri="${instruct_polling_start_lambda_arn}",
    aws_iam_arn="${instruct_polling_start_lambda_iam_role_arn}",
    tags=["models", "instruct", "chat"],
)
async def instruct_request(body: InstructRequest, user=Security(lambda_auth)):
    return InstructResponse()


# instruct polling response
@router.get(
    "/instruct/{message_id}",
    response_model=InstructResponse,
    aws_lambda_uri="${instruct_polling_check_lambda_arn}",
    aws_iam_arn="${instruct_polling_check_lambda_iam_role_arn}",
    tags=["models", "instruct", "chat"],
)
async def instruct_poll_response(user=Security(lambda_auth)):
    return


#
# tts
#
@router.post(
    "/tts",
    response_model=TTSResponse,
    aws_lambda_uri="${tts_polling_start_lambda_arn}",
    aws_iam_arn="${tts_polling_start_lambda_iam_role_arn}",
    tags=["models", "text-to-speech"],
)
async def tts(body: TTSRequest, user=Security(lambda_auth)):
    return TTSResponse()


@router.get(
    "/tts/{message_id}",
    response_model=TTSResponse,
    aws_lambda_uri="${tts_polling_check_lambda_arn}",
    aws_iam_arn="${tts_polling_check_lambda_iam_role_arn}",
    tags=["models", "text-to-speech"],
)
async def tts_poll_response(user=Security(lambda_auth)):
    return


@router.get(
    "/tts/{message_id}/{fieldname}",
    aws_s3_bucket="${s3_cache_object_bucket_name}",
    aws_object_key="{path}",
    aws_iam_arn="${s3_read_tts_object_iam_role_arn}",
    tags=["models", "text-to-speech"],
)
async def tts_object_response(user=Security(lambda_auth)):
    return


#
# usage
#
@router.get(
    "/usage/{key}/{period}",
    response_model=UsageResponse,
    aws_lambda_uri="${usage_stats_lambda_arn}",
    aws_iam_arn="${usage_stats_lambda_iam_role_arn}",
    tags=["usage"],
)
async def usage_stats_response(user=Security(lambda_auth)):
    return


#
# api spec
#
@router.get(
    "/openapi.json",
    aws_s3_bucket="${s3_assets_bucket_name}",
    aws_object_key="openapi.json",
    aws_iam_arn="${s3_read_api_object_iam_role_arn}",
    tags=["api"],
)
async def openapi_object_response(user=Security(lambda_auth)):
    return


@router.get(
    "/models.json",
    aws_s3_bucket="${s3_assets_bucket_name}",
    aws_object_key="models.json",
    aws_iam_arn="${s3_read_api_object_iam_role_arn}",
    tags=["api"],
)
async def model_descriptions_response(user=Security(lambda_auth)):
    return
