"""API request and response models.

Corresponds to package/src/api/models.py.

ModelUsageStats lives in shared.usage so handler modules and infrastructure
code can import it without depending on the API layer.
"""

from datetime import datetime
from typing import Dict, Generic, List, Literal, Optional, TypeVar

from pydantic import BaseModel, Field, field_validator
from shared.models import (Embedding, EmbeddingQuantization, InstructMessage,
                           InstructMessages, OutputReference)

from enum import Enum

T = TypeVar("T")


#
#
#

class ModelUsageStats(BaseModel):
    """Timing and resource statistics for one inference request.

    Not all fields are relevant for all model types; token counts are zero
    for image-in/image-out models.
    """

    duration:     int = Field(..., description="total process duration in milliseconds")
    inference:    int = Field(..., description="model inference duration in milliseconds")
    input_tokens: int = Field(0,   description="number of input tokens")
    output_tokens: int = Field(0,   description="number of output tokens")
    memory_usage: int = Field(..., description="peak process memory in KB")


# ---------------------------------------------------------------------------
# Submission and polling envelope types
# ---------------------------------------------------------------------------


class SubmissionResponse(BaseModel):
    """Returned by all POST submission endpoints.

    When status is present, a cached result was found and no job was queued.
    """

    message_id: str
    status: Optional[str] = None


class PollResponse(BaseModel, Generic[T]):
    """Returned by all GET /{mode}/{task}/{message_id} endpoints.

    status is one of: queued, processing, complete, error.
    result is present only when status is complete or error.
    """

    status: str
    message_id: str
    result: Optional[T] = None


class DeleteCacheResponse(BaseModel):
    status: Literal["ok"]


# ---------------------------------------------------------------------------
# Base request class
# ---------------------------------------------------------------------------


class EncryptionMethod(str, Enum):
    ECIES_SECP256K1_AES256GCM = "ecies-secp256k1-aes256gcm"


class EncryptionParams(BaseModel):
    method: EncryptionMethod = EncryptionMethod.ECIES_SECP256K1_AES256GCM
    pubkey: str    # base64-encoded secp256k1 compressed public key (33 bytes)

    @field_validator("pubkey")
    @classmethod
    def validate_pubkey(cls, v: str) -> str:
        import base64
        try:
            decoded = base64.b64decode(v)
        except Exception:
            raise ValueError("pubkey must be base64-encoded")
        if len(decoded) == 33 and decoded[0] in (0x02, 0x03):
            return v    # compressed
        if len(decoded) == 65 and decoded[0] == 0x04:
            return v    # uncompressed
        raise ValueError(
            "pubkey must be a secp256k1 key: "
            "33-byte compressed (0x02/0x03 prefix) or "
            "65-byte uncompressed (0x04 prefix)"
        )


class ModelRequest(BaseModel):
    """Common fields present on every model request."""

    model: str = Field(..., description="HuggingFace model identifier")
    seed: Optional[int] = Field(None, description="random seed for reproducible outputs")
    nonce: Optional[str] = Field(None, description="cache busting random field")
    encrypt: Optional[EncryptionParams] = Field(None, description="encryption method and key")

    @field_validator("model")
    @classmethod
    def normalise_model_name(cls, v: str) -> str:
        return v.lower()


# ---------------------------------------------------------------------------
# Embed
# ---------------------------------------------------------------------------


class EmbedRequest(ModelRequest):
    """Base for all embedding requests."""

    input: str = Field(..., description="content to embed")
    quantization: EmbeddingQuantization = Field(
        EmbeddingQuantization.FLOAT32,
        description="output vector quantization",
    )


class EmbedTextRequest(EmbedRequest):
    encoding_format: str = Field("float", description="ignored; use quantization")
    precision: int = Field(2, description="decimal places for float32 output")


class EmbedImageRequest(EmbedRequest):
    """Image embedding request. input must be base64-encoded."""


class EmbeddingResponse(BaseModel):
    model: str
    embedding: Embedding
    usage: ModelUsageStats


EmbedTextResponse = EmbeddingResponse


# ---------------------------------------------------------------------------
# Instruct
# ---------------------------------------------------------------------------


class InstructRequest(ModelRequest):
    messages: InstructMessages = Field(..., description="conversation turns")
    temperature: float = Field(1.0)
    max_tokens: int = Field(1000, description="maximum tokens to generate")
    top_k: Optional[int] = Field(None)
    top_p: Optional[float] = Field(None)
    min_p: Optional[float] = Field(None, description="minimum token probability as a fraction of the top token probability; range 0.0-1.0")
    repetition_penalty: Optional[float] = Field(None)
    no_repeat_ngram_size: Optional[int] = Field(None)


class InstructResponse(BaseModel):
    created: str = Field(default_factory=lambda: str(int(datetime.now().timestamp())))
    finish_reason: str = "stop"
    model: str
    choices: List[InstructMessage]
    usage: ModelUsageStats


# ---------------------------------------------------------------------------
# TTS
# ---------------------------------------------------------------------------


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
        ..., description="named S3 outputs; key 'audio' is the synthesised audio"
    )


# ---------------------------------------------------------------------------
# Txt2Audio
# ---------------------------------------------------------------------------


class Txt2AudioRequest(ModelRequest):
    prompt: str = Field(..., description="text description of the audio to generate")
    negative_prompt: Optional[str] = Field(
        None, description="AudioLDM2 only; description of qualities to avoid"
    )
    duration_seconds: float = Field(
        10.0,
        ge=1.0,
        le=30.0,
        description=(
            "length of the generated audio in seconds. "
            "MusicGen is capped at 30s. AudioLDM2 is uncapped but slow on CPU."
        ),
    )
    guidance_scale: float = Field(
        3.0,
        description="classifier-free guidance scale; higher values follow the prompt more closely",
    )
    num_inference_steps: Optional[int] = Field(
        None,
        description="diffusion steps for AudioLDM2; ignored for MusicGen. Defaults to 200.",
    )


class Txt2AudioResponse(BaseModel):
    created: str = Field(default_factory=lambda: str(int(datetime.now().timestamp())))
    finish_reason: str = "stop"
    model: str
    usage: ModelUsageStats
    outputs: Dict[str, OutputReference] = Field(
        ..., description="named S3 outputs; key 'audio' is the generated audio"
    )


# ---------------------------------------------------------------------------
# Txt2Img
# ---------------------------------------------------------------------------


class Txt2ImgRequest(ModelRequest):
    prompt: str = Field(..., description="generation prompt")
    negative_prompt: Optional[str] = None
    num_inference_steps: Optional[int] = Field(
        None,
        description=(
            "diffusion steps. Defaults to the NUM_STEPS env var on the ECS task "
            "(set per-model in models.yaml extra_env). Falls back to 10 if unset."
        ),
    )
    guidance_scale: float = Field(7.5, description="classifier-free guidance scale")


class Txt2ImgResponse(BaseModel):
    created: str = Field(default_factory=lambda: str(int(datetime.now().timestamp())))
    finish_reason: str = "stop"
    model: str
    usage: ModelUsageStats
    outputs: Dict[str, OutputReference] = Field(
        ..., description="named S3 outputs; key 'image' is the generated image"
    )


# ---------------------------------------------------------------------------
# Img2Txt
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Depth
# ---------------------------------------------------------------------------


class DepthRequest(ModelRequest):
    input: str = Field(..., description="base64 encoded input image")


class DepthResponse(BaseModel):
    created: str = Field(default_factory=lambda: str(int(datetime.now().timestamp())))
    model: str
    usage: ModelUsageStats
    outputs: Dict[str, OutputReference] = Field(
        ..., description="named S3 outputs; key 'depth' is the depth map"
    )


# ---------------------------------------------------------------------------
# Img2Mask
# ---------------------------------------------------------------------------


class Img2MaskRequest(ModelRequest):
    input: str = Field(..., description="base64 encoded input image")


class Img2MaskResponse(BaseModel):
    created: str = Field(default_factory=lambda: str(int(datetime.now().timestamp())))
    model: str
    usage: ModelUsageStats
    outputs: Dict[str, OutputReference] = Field(
        ..., description="named S3 outputs; key 'mask' is the segmentation mask"
    )


# ---------------------------------------------------------------------------
# Eval
# ---------------------------------------------------------------------------


class EvalTextRequest(ModelRequest):
    text: str = Field(..., description="text to evaluate")


class TextSimilarityRequest(ModelRequest):
    text1: str = Field(..., description="first text")
    text2: str = Field(..., description="second text to compare against")


class EvalImageRequest(ModelRequest):
    input: str = Field(..., description="base64 encoded image")


class ImageTextEvalRequest(ModelRequest):
    image: str = Field(..., description="base64 encoded image")
    text: str = Field(..., description="text to compare against the image")


class EvalScore(BaseModel):
    """One scored item from a text, image, or image-text evaluation.

    For sequence classification models (sentiment, toxicity, topic):
        label  -- the class label, e.g. "POSITIVE", "toxic"
        score  -- probability, 0.0 to 1.0

    For token classification models (NER, PII detection):
        entity_group -- entity type, e.g. "PER", "private_email"
        score        -- confidence, 0.0 to 1.0
        word         -- the matched text span
        start        -- character offset of span start
        end          -- character offset of span end

    For image and image-text evaluation (CLIP-based):
        label  -- the evaluated property, e.g. "aesthetic", "alignment"
        score  -- normalised score, 0.0 to 1.0
    """
    label:        Optional[str] = None
    score:        float
    entity_group: Optional[str] = None
    word:         Optional[str] = None
    start:        Optional[int] = None
    end:          Optional[int] = None


class EvalResponse(BaseModel):
    created: str = Field(default_factory=lambda: str(int(datetime.now().timestamp())))
    model:   str
    scores:  List[EvalScore]
    usage:   ModelUsageStats


# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------


UsageResponse = List[ModelUsageStats]
