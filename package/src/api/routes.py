from fastapi import Security

from fastapi_aws import AWSAPIRouter, LambdaAuthorizer

from .models import ListModelsResponse
from .models import EmbedTextRequest, EmbedImageRequest, EmbeddingsResponse
from .models import InstructRequest, InstructResponse
from .models import TTSRequest, TTSResponse


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
#    description="call the embed text model directly, with no polling buffer. NB: this call may fail",
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
# direct invocation can happen like this:
#    aws_sfn_sync_arn="${instruct_step_function_arn}",
#    aws_iam_arn="${instruct_step_function_iam_role_arn}",
    tags=["models", "instruct", "chat"],
)
async def instruct_new_message(body: InstructRequest, user=Security(lambda_auth)):
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
    aws_sfn_sync_arn="${tts_step_function_arn}",
    aws_iam_arn="${tts_step_function_iam_role_arn}",
    tags=["models", "text-to-speech"],
)
async def tts(body: TTSRequest, user=Security(lambda_auth)):
    return TTSResponse()
