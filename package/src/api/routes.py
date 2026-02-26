from fastapi import Security

from fastapi_aws import AWSAPIRouter, APIKeyAuthorizer, CognitoAuthorizer

from .models import EmbedTextRequest, EmbedImageRequest, EmbeddingsResponse
from .models import InstructRequest, InstructResponse
from .models import TTSRequest, TTSResponse
from .models import UsageResponse
from .models import DeleteCacheResponse


apikey_auth = APIKeyAuthorizer(
    authorizer_name="${apikey_authorizer_name}"
)

#cognito_auth = CognitoAuthorizer(
#    authorizer_name="${cognito_authorizer_name}"
#)
cognito_auth = None

router = AWSAPIRouter()


#
# embedding models
#
@router.post(
    "/embed/text",
    description="embed text into a feature space",
    response_model=EmbeddingsResponse,
    aws_lambda_arn="${polling_start_lambda_arn}",
    aws_iam_arn="${polling_start_lambda_iam_role_arn}",
    tags=["models", "embedding"],
)
async def embed_text(body: EmbedTextRequest, user=Security(apikey_auth)):
    return EmbeddingsResponse()


@router.get(
    "/embed/text/{message_id}",
    description="retrieve previously computed embeddings",
    response_model=EmbeddingsResponse,
    aws_lambda_arn="${polling_start_lambda_arn}",
    aws_iam_arn="${polling_start_lambda_iam_role_arn}",
    tags=["models", "embedding"],
)
async def fetch_embed_text(user=Security(apikey_auth)):
    return EmbeddingsResponse()


@router.delete(
    "/embed/text/{message_id}",
    description="delete a cached response",
    response_model=DeleteCacheResponse,
    aws_lambda_arn="${polling_start_lambda_arn}",
    aws_iam_arn="${polling_start_lambda_iam_role_arn}",
    tags=["models", "embedding"],
)
async def delete_embed_text_response(user=Security(apikey_auth)):
    return DeleteCacheResponse()


@router.post(
    "/embed/image",
    response_model=EmbeddingsResponse,
    aws_lambda_arn="${polling_start_lambda_arn}",
    aws_iam_arn="${polling_start_lambda_iam_role_arn}",
    tags=["models", "embedding"],
)
async def embed_image(body: EmbedImageRequest, user=Security(apikey_auth)):
    return EmbeddingsResponse()


#
# instruct
#
@router.post(
    "/instruct",
    response_model=InstructResponse,
    aws_lambda_arn="${polling_start_lambda_arn}",
    aws_iam_arn="${polling_start_lambda_iam_role_arn}",
    tags=["models", "instruct", "chat"],
)
async def instruct_request(body: InstructRequest, user=Security(apikey_auth)):
    return InstructResponse()


@router.get(
    "/instruct/{message_id}",
    response_model=InstructResponse,
    aws_lambda_arn="${polling_start_lambda_arn}",
    aws_iam_arn="${polling_start_lambda_iam_role_arn}",
    tags=["models", "instruct", "chat"],
)
async def instruct_poll_response(user=Security(apikey_auth)):
    return InstructResponse()


@router.delete(
    "/instruct/{message_id}",
    response_model=DeleteCacheResponse,
    aws_lambda_arn="${polling_start_lambda_arn}",
    aws_iam_arn="${polling_start_lambda_iam_role_arn}",
    tags=["models", "instruct", "chat"],
)
async def delete_instruct_cache_response(user=Security(apikey_auth)):
    return DeleteCacheResponse()


#
# tts
#
@router.post(
    "/tts",
    response_model=TTSResponse,
    aws_lambda_arn="${polling_start_lambda_arn}",
    aws_iam_arn="${polling_start_lambda_iam_role_arn}",
    tags=["models", "text-to-speech"],
)
async def tts(body: TTSRequest, user=Security(apikey_auth)):
    return TTSResponse()


@router.get(
    "/tts/{message_id}",
    aws_lambda_arn="${polling_start_lambda_arn}",
    aws_iam_arn="${polling_start_lambda_iam_role_arn}",
    response_model=TTSResponse,
    tags=["models", "text-to-speech"],
)
async def tts_poll_response(user=Security(apikey_auth)):
    return


#
# binary output retrieval
#
# All model types that produce binary outputs (audio, image, mesh, etc) write
# to S3 under the key schema: outputs/{model_type}/{message_id}/{field_name}
#
# The polling response includes an OutputReference for each named output field,
# and clients fetch the content via this single route.
#
# Model-specific convenience routes below map to the same S3 integration with
# fixed field names, avoiding the need for clients to inspect the polling
# response to discover output field names.
#
@router.get(
    "/output/{message_id}/{field_name}",
    description="retrieve a named binary output for a completed model invocation",
    aws_s3_bucket="${s3_output_bucket_name}",
    aws_s3_object_key="outputs/{message_id}/{field_name}",
    aws_iam_arn="${s3_read_output_iam_role_arn}",
    tags=["output"],
)
async def get_output(user=Security(apikey_auth)):
    return


@router.get(
    "/tts/{message_id}/audio",
    description="retrieve audio output for a completed TTS invocation",
    aws_s3_bucket="${s3_output_bucket_name}",
    aws_s3_object_key="outputs/text-to-speech/{message_id}/audio",
    aws_iam_arn="${s3_read_output_iam_role_arn}",
    tags=["models", "text-to-speech", "output"],
)
async def get_tts_audio(user=Security(apikey_auth)):
    return


@router.get(
    "/image/{message_id}/image",
    description="retrieve image output for a completed text-to-image invocation",
    aws_s3_bucket="${s3_output_bucket_name}",
    aws_s3_object_key="outputs/image-generator/{message_id}/image",
    aws_iam_arn="${s3_read_output_iam_role_arn}",
    tags=["models", "image-generation", "output"],
)
async def get_generated_image(user=Security(apikey_auth)):
    return


#
# usage
#
@router.get(
    "/usage/{key}/{period}",
    response_model=UsageResponse,
    aws_lambda_arn="${usage_stats_lambda_arn}",
    aws_iam_arn="${usage_stats_lambda_iam_role_arn}",
    tags=["usage"],
)
async def usage_stats_response(user=Security(apikey_auth)):
    return


#
# api spec
#
@router.get(
    "/openapi.json",
    aws_s3_bucket="${s3_assets_bucket_name}",
    aws_s3_object_key="openapi.json",
    aws_iam_arn="${s3_read_api_object_iam_role_arn}",
    tags=["api"],
)
async def openapi_object_response(user=Security(apikey_auth)):
    return


@router.get(
    "/models.json",
    aws_s3_bucket="${s3_assets_bucket_name}",
    aws_s3_object_key="models.json",
    aws_iam_arn="${s3_read_api_object_iam_role_arn}",
    tags=["api"],
)
async def model_descriptions_response(user=Security(apikey_auth)):
    return


#
# api key management
#
@router.post(
    "/users/keys",
    description="create an api key for programmatic access",
    aws_lambda_arn="${key_management_lambda_arn}",
    aws_iam_arn="${key_management_lambda_iam_role_arn}",
    tags=["keys"],
)
async def create_api_key(user=Security(cognito_auth)):
    return


@router.get(
    "/users/keys",
    description="list api keys for the current user",
    aws_lambda_arn="${key_management_lambda_arn}",
    aws_iam_arn="${key_management_lambda_iam_role_arn}",
    tags=["keys"],
)
async def list_api_keys(user=Security(cognito_auth)):
    return


@router.delete(
    "/users/keys/{key_id}",
    description="delete an api key",
    aws_lambda_arn="${key_management_lambda_arn}",
    aws_iam_arn="${key_management_lambda_iam_role_arn}",
    tags=["keys"],
)
async def delete_api_key(user=Security(cognito_auth)):
    return
