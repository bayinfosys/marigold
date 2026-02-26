"""module to define the enum types

this is so we can use enums without requiring pydantic.
when pydantic is available, import api.models fully

NB: enum values must match the MODEL_TYPE strings used in models.yaml and
    the _REGISTRY keys in models/__init__.py.  All three must be kept in sync.
"""

from enum import Enum


class ModelType(Enum):
    TEXT_EMBEDDING = "text-embedding"
    IMAGE_EMBEDDING = "image-embedding"
    INSTRUCT = "instruct"
    TTS = "tts"
    DEPTH = "depth"
    IMG2TXT = "img2txt"
    TXT2IMG = "txt2img"
    IMG2MASK = "img2mask"
    TXT2AUDIO = "txt2audio"
    IMG2MESH = "img2mesh"


class ModelModalities(Enum):
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    EMBEDDING = "embedding"
    MESH = "mesh"
