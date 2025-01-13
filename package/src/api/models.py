from enum import Enum

from pydantic import BaseModel, Field
from typing import List, Dict, Union


from datetime import datetime


from .enums import ModelType, ModelModalities


class CacheDestination(BaseModel):
    """Location of cached response in dynamodb
    This data is used to generate the key
    """
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


ListModelsResponse = List[ModelDescription]

Embedding = List[float]

EmbeddingsResponse = Embedding


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
    input_tokens: int = Field(..., description="number of tokens in the input")
    output_tokens: int = Field(..., description="number of tokens in the output")
    memory_usage: int = Field(..., description="process max memory usage in kb")


# embedding request/response
class EmbedTextRequest(BaseModel):
    model: str
    input: str
    encoding_format: str = Field("float", description="ignored")
    precision: int = Field("2", description="float precision of response")
    quantization: EmbeddingQuantization = Field(EmbeddingQuantization.FLOAT32, description="quantization method")


class EmbedImageRequest(BaseModel):
    model: str
    input: str


class EmbedTextResponse(BaseModel):
    model: str
    embedding: Embedding
    usage: ModelUsageStats


# deembedding
class DecodeTextResponse(BaseModel):
    model: str
    text: str
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


InstructMessageContentList = List[Union[InstructMessageTextContent, InstructMessageImageContent]]


class InstructMessageContentHF(BaseModel, use_enum_values=True):
    """Specific model type for huggingface library
    This is translated from our specific api type
    """
    type_: InstructMessageContentType = Field(default=InstructMessageContentType.TEXT, alias="type", description="optional type of the content in this message")
    text: str = Field(None, description="text content for instructions")

    class Config:
        exclude_none = True


class InstructMessage(BaseModel, use_enum_values=True):
    """this should match the openai structure
    NB: this structure should be inside a 'message' object
    TODO: add tokens and logprobs
    """
    role: InstructRole
    #type_: InstructType = Field(default=InstructType.TEXT, alias="type", description="optional type of the content for multi-modal models")
    content: Union[str, InstructMessageContentList] = Field(..., description="single text message or list of content types depending on model modality")


InstructMessages = List[InstructMessage]


class InstructResponse(BaseModel):
    #id: str = Field(None, description="unique id for this response (not used)")
    created: str = Field(default_factory=lambda: str(int(datetime.now().timestamp())))
    finish_reason: str = "stop"
    model: str
    choices: List[InstructMessage]
    usage: ModelUsageStats


class InstructRequest(BaseModel):
    model: str = Field(..., description="model to fulfill the request")
    messages: InstructMessages = Field(..., description="messages to be submitted")
    temperature: float = Field(1.0, description="ignored")
    max_tokens: int = Field(1000, description="maximum tokens to be generated")
    seed: int = Field(None, description="random seed for generation")
    top_k: int = Field(None, description="top_k tokens to consider")
    top_p: float = Field(None, description="nucleaus sampling by p")
    repetition_penalty: float = Field(None, description="increase to prevent repetition in output")
    no_repeat_ngram_size: int = Field(None, description="size of ngrams to prevent repeating")


class InstructSFNSubmission(BaseModel):
    """this is not used in the python, but is the input to sfn
    To use the /instruct_direct endpoint, use this message
    """
    destination: CacheDestination
    body: InstructRequest


# tts
class TTSResponse(BaseModel):
    data: str


class TTSRequest(BaseModel):
    lang_code: str
    input: str


# img2txt
class Img2TxtResponse(BaseModel):
    #id: str = Field(None, description="unique id for this response (not used)")
    created: str = Field(default_factory=lambda: str(int(datetime.now().timestamp())))
    finish_reason: str = "stop"
    model: str
    choices: List[InstructMessage]
    usage: ModelUsageStats


# usage response
UsageResponse = List[ModelUsageStats]
