"""module to define the enum types

this is so we can use enums without requiring pydantic.
when pydantic is available, import api.models fully
"""
from enum import Enum


class ModelType(Enum):
    TEXT_EMBEDDING = "text-embedding"
    IMAGE_EMBEDDING = "image-embedding"
    IMAGE_GEN = "image-generator"
    AUDIO_GEN = "audio-generator"
    TTS = "text-to-speech"
    INSTRUCT = "instruct"


class ModelModalities(Enum):
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    EMBEDDING = "embedding"
    MESH = "mesh"
