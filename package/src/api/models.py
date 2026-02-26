from datetime import datetime
from enum import Enum
from typing import Dict, Generic, List, Literal, Optional, TypeVar, Union

from pydantic import BaseModel, Field

from .enums import ModelModalities, ModelType

T = TypeVar("T")


# Infrastructure


class CacheDestination(BaseModel):
    """Location of a cached result in DynamoDB."""

    user_id: str
    message_id: str


class ModelProvider(BaseModel):
    name: str
    description: str
    links: Dict[str, str]


class ModelDescription(BaseModel):
    name: str
    type: ModelType
    description: str
    provider: ModelProvider
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


# the set of ModelDispatch is indexed by the md5 of the modelname
ModelDispatchRoutes = Dict[str, ModelDispatch]

ListModelsResponse = List[ModelDescription]


# Common types


Embedding = List[float]


class EmbeddingQuantization(str, Enum):
    """embedding quantization method to reduce storage requirements
    see: https://www.sbert.net/docs/package_reference/sentence_transformer/quantization.html#sentence_transformers.quantization.quantize_embeddings
    """

    FLOAT32 = "float32"
    INT8 = "int8"
    UINT8 = "uint8"
    BINARY = "binary"
    UBINARY = "ubinary"


class ModelUsageStats(BaseModel):
    """statistics around the processing
    NB: not all fields are relevant for all methods
    """

    duration: float = Field(..., description="process duration in seconds")
    inference: float = Field(..., description="inference duration in seconds")
    input_tokens: int = Field(..., description="number of input tokens")
    output_tokens: int = Field(..., description="number of output tokens")
    memory_usage: int = Field(..., description="peak process memory in KB")


class OutputReference(BaseModel):
    """Reference to a binary output stored in S3.
    Returned in model responses in place of inline binary data.
    The path follows the schema: outputs/{model_type}/{message_id}/{field_name}
    """

    path: str = Field(..., description="S3 object key")
    mimetype: str = Field(..., description="MIME type of the stored object")


# Submission and polling envelope types


class SubmissionResponse(BaseModel):
    """Returned by all POST submission endpoints.
    When status is present, a cached result was found and no job was queued.
    """

    message_id: str
    status: Optional[str] = None


class PollResponse(BaseModel, Generic[T]):
    """Returned by all GET /{model_type}/{message_id} endpoints.

    status is one of: "started", "running", "complete", "error".
    result is present only when status is "complete" or "error".
    """

    status: str
    message_id: str
    result: Optional[T] = None


class DeleteCacheResponse(BaseModel):
    status: Literal["ok"]


# Base request class


class ModelRequest(BaseModel):
    """Common fields present on every model request.

    All concrete request types inherit from this. Handlers and dispatch code
    can rely on `model` and `seed` being present without casting.
    """

    model: str = Field(..., description="HuggingFace model identifier")
    seed: Optional[int] = Field(
        None, description="random seed for reproducible outputs"
    )


# Embedding


class EmbedRequest(ModelRequest):
    """Base for all embedding requests.

    input carries the content to embed: a plain string for text, or a
    base64-encoded string (optionally with data-URI prefix) for image.

    quantization applies to all embedding outputs and defaults to float32.
    """

    input: str = Field(..., description="content to embed")
    quantization: EmbeddingQuantization = Field(
        EmbeddingQuantization.FLOAT32,
        description="output vector quantization",
    )


class EmbedTextRequest(EmbedRequest):
    """Text embedding request.

    encoding_format is accepted for OpenAI API compatibility but ignored;
    quantization controls the actual output format.
    precision controls decimal places in float32 outputs.
    """

    encoding_format: str = Field("float", description="ignored; use quantization")
    precision: int = Field(2, description="decimal places for float32 output")


class EmbedImageRequest(EmbedRequest):
    """Image embedding request.

    input must be a base64-encoded image, optionally prefixed with a
    data-URI header (data:image/jpeg;base64,...).
    """



class EmbeddingResponse(BaseModel):
    model: str
    embedding: Embedding
    usage: ModelUsageStats


# instruct


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
    """Message content can be either (a) a string, or (b) a dict(type, text)"""

    text: str = Field(..., description="instruction text")


InstructMessageContentList = List[
    Union[InstructMessageTextContent, InstructMessageImageContent]
]


class InstructMessageContentHF(BaseModel, use_enum_values=True):
    """HuggingFace chat template content item, translated from InstructMessage."""

    type_: InstructMessageContentType = Field(
        default=InstructMessageContentType.TEXT,
        alias="type",
        description="optional type of the content in this message",
    )
    text: str = Field(None, description="text content for instructions")

    class Config:
        exclude_none = True


class InstructMessage(BaseModel, use_enum_values=True):
    """One turn in a conversation. Matches the OpenAI message structure."""

    role: InstructRole
    content: Union[str, InstructMessageContentList] = Field(
        ...,
        description="plain string or list of typed content items",
    )


InstructMessages = List[InstructMessage]


class InstructRequest(ModelRequest):
    messages: InstructMessages = Field(..., description="conversation turns")
    temperature: float = Field(1.0, description="ignored")
    max_tokens: int = Field(1000, description="maximum tokens to generate")
    top_k: int = Field(None, description="top-k sampling")
    top_p: float = Field(None, description="nucleus sampling p")
    repetition_penalty: float = Field(None, description="penalty for repeated tokens")
    no_repeat_ngram_size: int = Field(None, description="n-gram repetition window")


class InstructResponse(BaseModel):
    created: str = Field(default_factory=lambda: str(int(datetime.now().timestamp())))
    finish_reason: str = "stop"
    model: str
    choices: List[InstructMessage]
    usage: ModelUsageStats


# tts


class TTSRequest(ModelRequest):
    language_code: str = Field(..., description="BCP-47 language code, e.g. en/GB")
    text: str = Field(..., description="text to synthesise")


class TTSResponse(BaseModel):
    created: str = Field(default_factory=lambda: str(int(datetime.now().timestamp())))
    finish_reason: str = "stop"
    model: str
    usage: ModelUsageStats
    language_code: str
    outputs: Dict[str, OutputReference] = Field(
        ..., description="named S3 outputs; key 'audio' is the audio file"
    )


# txt2img


class Txt2ImgRequest(ModelRequest):
    prompt: str = Field(..., description="generation prompt")
    negative_prompt: Optional[str] = None
    num_inference_steps: int = Field(20, description="diffusion steps")
    guidance_scale: float = Field(7.5, description="classifier-free guidance scale")


class Txt2ImgResponse(BaseModel):
    created: str = Field(default_factory=lambda: str(int(datetime.now().timestamp())))
    finish_reason: str = "stop"
    model: str
    usage: ModelUsageStats
    outputs: Dict[str, OutputReference] = Field(
        ..., description="named S3 outputs; key 'image' is the generated image"
    )


# img2txt


class Img2TxtRequest(ModelRequest):
    input: str = Field(..., description="base64 encoded image")
    prompt: Optional[str] = None
    max_tokens: int = Field(500, description="maximum tokens to generate")


class Img2TxtResponse(BaseModel):
    created: str = Field(default_factory=lambda: str(int(datetime.now().timestamp())))
    finish_reason: str = "stop"
    model: str
    choices: List[InstructMessage]
    usage: ModelUsageStats


# depth estimation


class DepthRequest(ModelRequest):
    input: str = Field(..., description="base64 encoded input image")


class DepthResponse(BaseModel):
    created: str = Field(default_factory=lambda: str(int(datetime.now().timestamp())))
    model: str
    usage: ModelUsageStats
    outputs: Dict[str, OutputReference] = Field(
        ..., description="named S3 outputs; key 'depth' is the depth map"
    )


# img2mask


class Img2MaskRequest(ModelRequest):
    input: str = Field(..., description="base64 encoded input image")


class Img2MaskResponse(BaseModel):
    created: str = Field(default_factory=lambda: str(int(datetime.now().timestamp())))
    model: str
    usage: ModelUsageStats
    outputs: Dict[str, OutputReference] = Field(
        ..., description="named S3 outputs; key 'mask' is the segmentation mask"
    )


# Usage


UsageResponse = List[ModelUsageStats]
