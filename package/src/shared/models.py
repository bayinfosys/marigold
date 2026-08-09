"""Common object definitions whic hare not request and response models."""
from enum import Enum
from typing import Dict, List, TypeVar, Union, Any

import httpx

from pydantic import BaseModel, Field, field_validator
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


class OutputMimeType(str, Enum):
    IMAGE_PNG  = "image/png"
    IMAGE_JPEG = "image/jpeg"
    AUDIO_MP3  = "audio/mpeg"
    VIDEO_MP4  = "video/mp4"

    @property
    def extension(self) -> str:
        _MAP = {
            "image/png":  "png",
            "image/jpeg": "jpg",
            "audio/mpeg": "mp3",
            "video/mp4":  "mp4",
        }
        return _MAP.get(self.value, "bin")


class OutputReference(BaseModel):
    """Reference to a binary output.

    Returned in model responses in place of inline binary data.
    Key schema: outputs/{model_type}/{message_id}/{field_name}
    """

    path: str = Field(..., description="object key")
    mimetype: str = Field(..., description="MIME type of the stored object")


# ---------------------------------------------------------------------------
# Instruct
# ---------------------------------------------------------------------------


class InstructRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class InstructMessageContentType(str, Enum):
    TEXT = "text"
    IMAGE = "image"


class InstructMessageImageContent(BaseModel):
    """image: str = Field(..., description="base64 encoded image prompt")

    NOTE: accepted by this schema but not implemented. models/instruct.py
    never decodes or forwards image content -- its loader
    (AutoModelForCausalLM + AutoTokenizer) has no vision capability. For
    image input today, use /gen/img2txt (single image + prompt, no chat
    history) instead. See TODO.md, "No multimodal chat".
    """
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
    content: Union[str, InstructMessageContentList, None] = Field(...)
    tool_calls: list[Dict] = Field(default_factory=list)

    @field_validator("role", mode="before")
    @classmethod
    def coerce_role(cls, v):
        if isinstance(v, InstructRole):
            return v

        return InstructRole(v)


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
