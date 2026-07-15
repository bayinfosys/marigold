"""Shared enumerations.

Importable without pulling in boto3, pydantic, or any ML dependencies.
All three enum classes must be kept in sync with:
  - models.yaml  (type/mode strings)
  - _SPECS registry  (ModelType values used as keys)
"""

from enum import Enum, StrEnum


class ModelProvider(str, Enum):
    """Provider of a model's weights.

    Values are stable strings stored in models.yaml and used for dispatch
    in the tools layer. Do not rename values without updating all models.yaml
    entries.
    """

    HUGGINGFACE = "huggingface"
    AWS_BEDROCK = "aws-bedrock"
    OLLAMA = "ollama"
    TOOLS = "tools"


class ModelType(StrEnum):
    """Unique identifier for each task type.

    Values are stable strings stored in DynamoDB, S3 key prefixes, ECS
    task environment variables, and models.yaml. Do not rename values
    without a coordinated migration of all stored data.
    """

    TEXT_EMBEDDING   = "text-embedding"
    IMAGE_EMBEDDING  = "image-embedding"
    INSTRUCT         = "instruct"
    TTS              = "tts"
    TXT2AUDIO        = "txt2audio"
    DEPTH            = "depth"
    IMG2TXT          = "img2txt"
    TXT2IMG          = "txt2img"
    IMG2MASK         = "img2mask"
    TEXT_EVAL        = "text-eval"
    TEXT_SIMILARITY  = "text-similarity"
    IMAGE_EVAL       = "image-eval"
    IMAGE_TEXT_EVAL  = "image-text-eval"
    HTTP             = "http"
    # --- audio ---
    ASR              = "asr"
    # --- video ---
    TXT2VID          = "txt2vid"
    IMG2VID          = "img2vid"
    VID2TXT          = "vid2txt"
    # --- embodied / robot ---
    OBS2ACT          = "obs2act"
    # --- 3d ---
    IMG23D           = "img23d"


class ModelMode(Enum):
    """Top-level API grouping.

    Determines the URL prefix and the generic poll/delete route namespace:
        /embed/{task}/{message_id}
        /eval/{task}/{message_id}
        /gen/{task}/{message_id}
    """

    EMBED = "embed"
    EVAL  = "eval"
    GEN   = "gen"


class OutputMimeType(Enum):
    """MIME types produced by model handlers.

    The storage property determines whether an output field is written to
    S3 (binary types) or DynamoDB (text and JSON types).
    """

    JSON        = "application/json"
    TEXT        = "text/plain"
    IMAGE_PNG   = "image/png"
    IMAGE_JPEG  = "image/jpeg"
    AUDIO_MP3   = "audio/mpeg"
    AUDIO_WAV   = "audio/wav"
    VIDEO_MP4   = "video/mp4"
    MESH_GLB    = "model/gltf-binary"

    @property
    def storage(self) -> str:
        if self.value.startswith(("image/", "audio/", "video/", "model/")):
            return "s3"
        return "dynamodb"


class ModelModalities(Enum):
    TEXT      = "text"
    IMAGE     = "image"
    AUDIO     = "audio"
    VIDEO     = "video"
    EMBEDDING = "embedding"
    MESH      = "mesh"
