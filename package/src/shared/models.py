"""Common object definitions which are not request and response models."""
import json
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, TypeVar, Union

import httpx

from pydantic import BaseModel, Field, field_validator, model_validator
from shared.enums import ModelModalities, ModelProvider, ModelType

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Infrastructure
# ---------------------------------------------------------------------------


class CacheDestination(BaseModel):
    """Location of a cached result in the results table."""

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


class OutputReference(BaseModel):
    """Reference to a binary output in the object store.

    Returned in model responses in place of inline binary data. Fetch the
    bytes from GET /output/{mode}/{task}/{message_id}/{field}.

    Key schema: outputs/{model_type}/{message_id}_{field_name}.{ext}
    """

    path: str = Field(..., description="object key")
    mimetype: str = Field(..., description="MIME type of the stored object")
    bytes: Optional[int] = Field(None, description="size of the stored object")
    sha256: Optional[str] = Field(None, description="sha256 of the stored object, hex")


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


def gen_tool_call_id(message_id: str, index: int) -> str:
    """The id of the index-th tool call in the reply to message_id.

    Derived rather than random: a cached result returns the same ids every
    time it is read, and the native and OpenAI routes agree on them.
    """
    return "call_%s_%d" % (message_id.removeprefix("API#")[:8], index)


class InstructToolCallFunction(BaseModel):
    name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("arguments", mode="before")
    @classmethod
    def parse_string_arguments(cls, v):
        """The OpenAI wire format carries arguments as a JSON string."""
        if isinstance(v, str):
            return json.loads(v) if v.strip() else {}
        return v


class InstructToolCall(BaseModel):
    """One tool call in an assistant turn, in the OpenAI shape."""

    id: str = Field("", description="matches the tool_call_id of the tool message answering it")
    type: Literal["function"] = "function"
    function: InstructToolCallFunction

    @model_validator(mode="before")
    @classmethod
    def accept_flat_shape(cls, v):
        """Results stored before 0.8 hold the flat {"name", "arguments"} shape."""
        if isinstance(v, dict) and "function" not in v and "name" in v:
            return {
                "id": v.get("id", ""),
                "type": "function",
                "function": {"name": v["name"], "arguments": v.get("arguments", {})},
            }
        return v


class InstructMessage(BaseModel, use_enum_values=True):
    """One turn in a conversation. Matches the OpenAI message structure.

    An assistant turn may carry tool_calls; the tool message answering
    one carries its id in tool_call_id.
    """

    role: InstructRole
    content: Union[str, InstructMessageContentList, None] = Field(...)
    tool_calls: List[InstructToolCall] = Field(default_factory=list)
    tool_call_id: Optional[str] = Field(None, description="on a tool message: the call it answers")
    name: Optional[str] = Field(None, description="on a tool message: the tool's name")

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
