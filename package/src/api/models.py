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
    memory_usage: int = Field(0, description="peak process memory in KB")
    load_time_ms:     int = Field(0,   description="model load time in ms")
    model_size_bytes: int = Field(0,   description="model size in bytes")
    vram_usage_bytes: int = Field(0,   description="VRAM allocated during inference bytes")
    vram_usage_bytes_peak: int = Field(0, description="peak VRAM allocated during inference, bytes")
    power_watts_peak: float = Field(0.0, description="peak GPU power draw during inference, watts")
    power_watts_mean: float = Field(0.0, description="mean GPU power draw during inference, watts")
    cpu_offload_bytes: int = Field(0, description="model bytes offloaded off-GPU at load time")


class ModelResponse(BaseModel):
    """Root base for all model responses.

    Every response carries the model identifier and usage statistics.
    Subclasses add fields appropriate to their output category.
    """
    model: str
    usage: ModelUsageStats


class GenerativeResponse(ModelResponse):
    """Base for responses from generative and transformative models.

    Adds a creation timestamp and a finish reason. All models that
    produce content (text, audio, image, video, actions) use this base.
    Embedding and evaluation responses use ModelResponse directly.
    """
    created: str = Field(
        default_factory=lambda: str(int(datetime.now().timestamp()))
    )
    finish_reason: str = "stop"


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


class EmbeddingResponse(ModelResponse):
    embedding: Embedding


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
    tools: list[Dict] = Field(default_factory=list, description="JSON schema function tool definitions")


class InstructResponse(GenerativeResponse):
    choices: List[InstructMessage]


# ---------------------------------------------------------------------------
# TTS
# ---------------------------------------------------------------------------


class TTSRequest(ModelRequest):
    language_code: str = Field(..., description="BCP-47 language code, e.g. en/GB")
    text: str = Field(..., description="text to synthesise")


class TTSResponse(GenerativeResponse):
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


class Txt2AudioResponse(GenerativeResponse):
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


class Txt2ImgResponse(GenerativeResponse):
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


class Img2TxtResponse(GenerativeResponse):
    choices: List[InstructMessage]


# ---------------------------------------------------------------------------
# Depth
# ---------------------------------------------------------------------------


class DepthRequest(ModelRequest):
    input: str = Field(..., description="base64 encoded input image")


class DepthResponse(GenerativeResponse):
    outputs: Dict[str, OutputReference] = Field(
        ..., description="named S3 outputs; key 'depth' is the depth map"
    )


# ---------------------------------------------------------------------------
# Img2Mask
# ---------------------------------------------------------------------------


class Img2MaskRequest(ModelRequest):
    input: str = Field(..., description="base64 encoded input image")


class Img2MaskResponse(GenerativeResponse):
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


class EvalResponse(ModelResponse):
    created: str = Field(default_factory=lambda: str(int(datetime.now().timestamp())))
    scores:  List[EvalScore]


# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------


UsageResponse = List[ModelUsageStats]


# ---------------------------------------------------------------------------
# Demo Chat
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    messages:    List[InstructMessage]
    system:      Optional[str]   = None
    temperature: Optional[float] = Field(0.7, ge=0.0, le=2.0)
    max_tokens:  Optional[int]   = Field(500,  ge=1, le=4096)
    nonce:       Optional[str]   = None


# ---------------------------------------------------------------------------
# Txt2Vid
# ---------------------------------------------------------------------------


class Txt2VidRequest(ModelRequest):
    prompt: str = Field(..., description="generation prompt")
    negative_prompt: Optional[str] = Field(
        None,
        description="qualities to suppress; supported by CogVideoX and similar models",
    )
    num_frames: int = Field(
        49,
        ge=1,
        description=(
            "number of frames to generate. CogVideoX-5b default is 49 (approx 6s at 8fps). "
            "Must be 4k+1 for most DiT video models (e.g. 49, 81, 97)"
        ),
    )
    fps: int = Field(
        8,
        ge=1,
        le=60,
        description="frames per second of the output video",
    )
    num_inference_steps: Optional[int] = Field(
        None,
        description=(
            "diffusion steps. Defaults to NUM_STEPS env var on the ECS task. "
            "Falls back to 50 if unset"
        ),
    )
    guidance_scale: float = Field(
        6.0,
        description="classifier-free guidance scale",
    )
    width: Optional[int] = Field(
        None,
        description="output width in pixels; defaults to the model's native resolution",
    )
    height: Optional[int] = Field(
        None,
        description="output height in pixels; defaults to the model's native resolution",
    )


class Txt2VidResponse(BaseModel):
    created: str = Field(default_factory=lambda: str(int(datetime.now().timestamp())))
    finish_reason: str = "stop"
    model: str
    usage: ModelUsageStats
    num_frames: int
    fps: int
    outputs: Dict[str, OutputReference] = Field(
        ..., description="named S3 outputs; key 'video' is the generated video"
    )


# ---------------------------------------------------------------------------
# Vid2Txt
# ---------------------------------------------------------------------------


class Vid2TxtRequest(ModelRequest):
    input: str = Field(
        ...,
        description=(
            "video to describe. Accepts base64-encoded video or an "
            "s3://bucket/key URI. Short clips only for base64; use S3 for "
            "anything over ~10MB"
        ),
    )
    prompt: Optional[str] = Field(
        None,
        description=(
            "optional question or instruction. When None, the model produces "
            "a general description of the video content"
        ),
    )
    max_tokens: int = Field(500, description="maximum tokens to generate")


class Vid2TxtResponse(BaseModel):
    created: str = Field(default_factory=lambda: str(int(datetime.now().timestamp())))
    finish_reason: str = "stop"
    model: str
    choices: List[InstructMessage]
    usage: ModelUsageStats


# ---------------------------------------------------------------------------
# Img23D
# ---------------------------------------------------------------------------


class Img23DRequest(ModelRequest):
    input: str = Field(
        ...,
        description="base64 encoded input image. A clean subject on a plain "
                    "background produces the best reconstruction",
    )
    remove_background: bool = Field(
        True,
        description=(
            "run background removal before reconstruction. Set to False if "
            "the image already has a transparent or uniform background"
        ),
    )
    num_views: Optional[int] = Field(
        None,
        description=(
            "number of intermediate views to generate during reconstruction. "
            "Higher values improve quality at the cost of compute. "
            "Defaults to the model's recommended value when None"
        ),
    )


class Img23DResponse(BaseModel):
    created: str = Field(default_factory=lambda: str(int(datetime.now().timestamp())))
    model: str
    usage: ModelUsageStats
    outputs: Dict[str, OutputReference] = Field(
        ...,
        description="named S3 outputs; key 'mesh' is the GLB file",
    )


# ---------------------------------------------------------------------------
# ASR
# ---------------------------------------------------------------------------


class ASRRequest(ModelRequest):
    input: str = Field(
        ...,
        description=(
            "audio to transcribe. Accepts base64-encoded audio (any format "
            "ffmpeg can decode) or an s3://bucket/key URI for larger files"
        ),
    )
    language: Optional[str] = Field(
        None,
        description=(
            "BCP-47 language code of the spoken language, e.g. 'en', 'fr'. "
            "When None, the model performs language detection if supported"
        ),
    )
    return_timestamps: bool = Field(
        False,
        description=(
            "request time-aligned segment boundaries in the response. "
            "Ignored by models that do not support timestamp output"
        ),
    )


class ASRSegment(BaseModel):
    """One time-aligned segment from a transcription.

    start and end are in seconds from the beginning of the audio.
    confidence is a normalised score in the range 0.0 to 1.0 where
    available; None when the model does not produce per-segment confidence.
    """

    id: int
    start: float
    end: float
    text: str
    confidence: Optional[float] = None


class ASRResponse(GenerativeResponse):
    language: str = Field(..., description="detected or specified BCP-47 language code")
    text: str = Field(..., description="full transcript as a single string")
    segments: Optional[List[ASRSegment]] = Field(
        None,
        description="per-segment detail; present only when return_timestamps=True",
    )


# ---------------------------------------------------------------------------
# Img2Vid
# ---------------------------------------------------------------------------


class VideoKeyframe(BaseModel):
    """One image anchor in a video generation sequence.

    image is a base64-encoded RGB image.

    timestamp is the position of this frame in seconds from the start of
    the output video. When None, the handler distributes keyframes at
    uniform intervals across the requested duration. At least one keyframe
    at timestamp=0.0 (or with timestamp=None) is required to establish
    the starting frame.

    Models that do not support multi-keyframe conditioning use keyframes[0]
    as the single conditioning image and ignore the rest.
    """
    image: str = Field(..., description="base64 encoded RGB image")
    timestamp: Optional[float] = Field(
        None,
        ge=0.0,
        description="position in seconds from the start of the video; "
                    "None defers to handler-computed uniform spacing",
    )


class Img2VidRequest(ModelRequest):
    keyframes: List[VideoKeyframe] = Field(
        ...,
        min_length=1,
        description=(
            "one or more image anchors for the generation. "
            "A single keyframe produces standard image-to-video output. "
            "Two keyframes condition on start and end frames. "
            "Multiple keyframes are passed to models that support "
            "multi-reference conditioning"
        ),
    )
    prompt: Optional[str] = Field(
        None,
        description=(
            "optional text conditioning. Ignored by models that do not "
            "support text-conditioned image-to-video generation"
        ),
    )
    negative_prompt: Optional[str] = None
    num_frames: int = Field(25, ge=1, description="number of frames to generate")
    fps: int = Field(8, ge=1, le=60, description="frames per second of the output video")
    num_inference_steps: Optional[int] = Field(None, description="diffusion steps; defaults to NUM_STEPS env var, falls back to 25")
    guidance_scale: float = Field(7.5, description="classifier-free guidance scale")

class Img2VidResponse(GenerativeResponse):
    num_frames: int
    fps: int
    outputs: Dict[str, OutputReference] = Field(
        ..., description="named S3 outputs; key 'video' is the generated video"
    )


# ---------------------------------------------------------------------------
# Obs2Act
# ---------------------------------------------------------------------------


class Obs2ActRequest(ModelRequest):
    image: str = Field(
        ...,
        description="base64 encoded RGB observation image from the robot camera",
    )
    instruction: str = Field(
        ...,
        description="natural language task instruction, e.g. 'pick up the red block'",
    )
    state: Optional[List[float]] = Field(
        None,
        description=(
            "current robot state vector. Layout is model-dependent: typically "
            "joint positions followed by end-effector pose. Pass None if the "
            "model does not use state input"
        ),
    )


class Obs2ActResponse(GenerativeResponse):
    choices: List[InstructMessage]


# ---------------------------------------------------------------------------
# Vid2Vid
# ---------------------------------------------------------------------------


class Vid2VidRequest(ModelRequest):
    input: str = Field(
        ...,
        description=(
            "source video to transform. Accepts base64-encoded video or an "
            "s3://bucket/key URI"
        ),
    )
    prompt: Optional[str] = Field(
        None,
        description=(
            "optional text conditioning. Guides the transformation toward "
            "the described content. Ignored by models that do not support "
            "text conditioning"
        ),
    )
    negative_prompt: Optional[str] = None
    strength: float = Field(
        0.7,
        ge=0.0,
        le=1.0,
        description=(
            "transformation strength. 0.0 returns output close to the input; "
            "1.0 allows the model to deviate fully from the source video"
        ),
    )
    num_inference_steps: Optional[int] = Field(
        None,
        description="diffusion steps; defaults to NUM_STEPS env var, falls back to 50",
    )
    guidance_scale: float = Field(7.5, description="classifier-free guidance scale")
    fps: int = Field(
        8,
        ge=1,
        le=60,
        description="frames per second of the output video",
    )


class Vid2VidResponse(GenerativeResponse):
    num_frames: int
    fps: int
    outputs: Dict[str, OutputReference] = Field(
        ..., description="named S3 outputs; key 'video' is the transformed video"
    )
