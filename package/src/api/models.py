from enum import StrEnum
from pydantic import BaseModel, Field
from typing import Literal, Optional
from typing import List, Dict, Any


from datetime import datetime


class ModelType(StrEnum):
    TEXT_EMBEDDING = "text-embedding"
    IMAGE_EMBEDDING = "image-embedding"
    IMAGE_GEN = "image-generator"
    AUDIO_GEN = "audio-generator"
    TTS = "text-to-speech"
    INSTRUCT = "instruct"


class ModelModalities(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    EMBEDDING = "embedding"
    MESH = "mesh"


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


class ModelUsageStats(BaseModel):
    """statistics around the processing
    NB: not all fields are relevant for all methods
    """
    duration: float = Field(..., description="process duration in seconds")
    inference: float = Field(..., description="inference duration in seconds")
    input_tokens: int = Field(..., description="number of tokens in the input")
    output_tokens: int = Field(..., description="number of tokens in the output")


# embedding request/response
class EmbedTextRequest(BaseModel):
    model: str
    input: str
    encoding_format: str = Field("float", description="ignored")
    precision: int = Field("2", description="float precision of response")


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
class InstructRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class InstructMessage(BaseModel):
    """this should match the openai structure
    NB: this structure should be inside a 'message' object
    TODO: add tokens and logprobs
    """

    role: InstructRole
    content: str


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
    user_id: str
    message_id: str
    input: InstructRequest


# tts
class TTSResponse(BaseModel):
    data: str


class TTSRequest(BaseModel):
    lang_code: str
    input: str
