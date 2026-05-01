"""Common object definitions whic hare not request and response models."""
from enum import Enum
from typing import Dict, List, TypeVar, Union, Any

import httpx

from pydantic import BaseModel, Field
from shared.enums import ModelModalities, ModelProvider, ModelType

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Infrastructure
# ---------------------------------------------------------------------------


class CacheDestination(BaseModel):
    """Location of a cached result in DynamoDB."""

    user_id: str
    message_id: str


class ProviderInfo(BaseModel):
    name: ModelProvider
    description: str
    links: Dict[str, str]


class ModelDescription(BaseModel):
    name: str
    type: ModelType
    description: str
    provider: ProviderInfo
    inputs: List[ModelModalities]
    outputs: List[ModelModalities]


class ModelDispatch(BaseModel):
    """Runtime routing config for a model, loaded by the polling lambda from S3.

    Contains only what is needed at dispatch time. Handler selection and
    environment configuration are resolved by Terraform at task-definition time.
    """

    queue_url: str
    task_definition: str
    family: str
    model_type: str


ModelDispatchRoutes = Dict[str, ModelDispatch]
ListModelsResponse = List[ModelDescription]


# ---------------------------------------------------------------------------
# Common types
# ---------------------------------------------------------------------------


Embedding = List[float]


class EmbeddingQuantization(str, Enum):
    """Embedding quantization method.

    See: https://www.sbert.net/docs/package_reference/sentence_transformer/quantization.html
    """

    FLOAT32 = "float32"
    INT8 = "int8"
    UINT8 = "uint8"
    BINARY = "binary"
    UBINARY = "ubinary"


class OutputReference(BaseModel):
    """Reference to a binary output stored in S3.

    Returned in model responses in place of inline binary data.
    Key schema: outputs/{model_type}/{message_id}/{field_name}
    """

    path: str = Field(..., description="S3 object key")
    mimetype: str = Field(..., description="MIME type of the stored object")


# ---------------------------------------------------------------------------
# Instruct
# ---------------------------------------------------------------------------


class InstructRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class InstructMessageContentType(str, Enum):
    TEXT = "text"
    IMAGE = "image"


class InstructMessageImageContent(BaseModel):
    image: str = Field(..., description="base64 encoded image prompt")


class InstructMessageTextContent(BaseModel):
    text: str = Field(..., description="instruction text")


InstructMessageContentList = List[
    Union[InstructMessageTextContent, InstructMessageImageContent]
]


class InstructMessageContentHF(BaseModel, use_enum_values=True):
    """HuggingFace chat template content item."""

    type_: InstructMessageContentType = Field(
        default=InstructMessageContentType.TEXT,
        alias="type",
    )
    text: str = Field(None)

    class Config:
        exclude_none = True


class InstructMessage(BaseModel, use_enum_values=True):
    """One turn in a conversation. Matches the OpenAI message structure."""

    role: InstructRole
    content: Union[str, InstructMessageContentList] = Field(...)


InstructMessages = List[InstructMessage]


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


class HttpRequest(BaseModel):
    url: str
    method: str = "GET"
    headers: Dict[str, str] = Field(..., default_factory=dict)
    body: Dict[str, Any] = Field(..., default_factory=dict)
    timeout: int = 30


class HttpResponse(BaseModel):
    status: int
    body: Dict[str, Any]
    headers: Dict[str, str]

    @classmethod
    def from_response(cls, response: httpx.Response) -> "HttpResponse":
        """parse a httpx response model into our own HttpResponse object
        NB: only "application/json" is allowed at the moment
        """
        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type:
            raise ValueError(
                f"Unsupported content type: {content_type}. "
                "Only application/json responses are supported."
            )
        return cls(
            status=response.status_code,
            body=response.json(),
            headers=dict(response.headers),
        )
