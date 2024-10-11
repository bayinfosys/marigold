from fastapi_aws import AWSAPIRouter, CognitoAuthorizer

from .models import ListModelsResponse
from .models import EmbedTextRequest, EmbedImageRequest, EmbeddingsResponse
from .models import InstructRequest, InstructResponse
from .models import TTSRequest, TTSResponse

cognito_auth = CognitoAuthorizer(authorizer_name="${cognito_authorizer_name}")

router = AWSAPIRouter()


#
# model descriptions
#
@router.get(
    "/models",
    response_model=ListModelsResponse,
    aws_integration_uri="${mdl_function_arn}",
    tags=["models"],
)
async def list_models():
    return ListModelsResponse()


#
# embedding models
#
@router.post(
    "/embed/text",
    response_model=EmbeddingsResponse,
    aws_integration_uri="${mdl_function_arn}",
    tags=["models", "embedding"],
)
async def embed_text(body: EmbedTextRequest):
    return EmbeddingsResponse()


@router.post(
    "/embed/image",
    response_model=EmbeddingsResponse,
    aws_integration_uri="${mdl_function_arn}",
    tags=["models", "embedding"],
)
async def embed_image(body: EmbedImageRequest):
    return EmbeddingsResponse()


#
# instruct
#
@router.post(
    "/instruct",
    response_model=InstructResponse,
    aws_integration_uri="${mdl_function_arn}",
    tags=["models", "instruct", "chat"],
)
async def instruct_new_message(body: InstructRequest):
    return InstructResponse()


# instruct polling response
@router.get(
    "/instruct/{message_id}",
    response_model=InstructResponse,
    aws_integration_uri="${mdl_function_arn}",
    tags=["models", "instruct", "chat"],
)
async def instruct_poll_response():
    return


#
# tts
#
@router.post(
    "/tts",
    response_model=TTSResponse,
    aws_integration_uri="${mdl_function_arn}",
    tags=["models", "text-to-speech"],
)
async def tts(body: TTSRequest):
    return TTSResponse()
