"""
shared/db_models.py -- DynamoDB item definitions for shared tables.

PK/SK patterns are the authoritative source for all key construction.
Values are sourced from CONTRACTS.md. No key strings are constructed
anywhere outside this module.

All items use boto3.client("dynamodb") wire format via to_dynamo_item().
Never use boto3.resource or Table objects with these items.
"""
import os
import json
import time
from hashlib import md5 as _md5
from typing import ClassVar, Optional

from dynawrap import DBItem
from pydantic import BaseModel, computed_field

from .schedule_models import LifecycleEvent
from .enums import ModelType, ModelProvider


_DEFAULT_TTL_OFFSET = 86400 * 30  # 30 days


_ENV_KEYS = ("LOAD_IN_4BIT", "USE_FAST", "TRUST_REMOTE_CODE", "LOW_CPU_MEM_USAGE")


def set_model_config_env(config_entry: "ModelCatalogueItem") -> None:
    """Apply a catalogue entry's extra_env to the process environment,
    clearing any previous entry's values first. Shared between worker.py
    (serve time) and model_cache_shared.py (cache-init time) so both load
    a model under the same settings.
    """
    for key in _ENV_KEYS:
        os.environ.pop(key, None)
    for key, value in config_entry.extra_env.items():
        os.environ[key] = value


class ResultsItem(DBItem, BaseModel):
    """One inference result record in the results cache.

    job_id is an opaque unique identifier for the inference job.
    The caller is responsible for constructing job_id before creating
    this record. ResultsItem has no knowledge of how job_id is derived.
    """

    pk_pattern: ClassVar[str] = "USER#{user_id}"
    sk_pattern: ClassVar[str] = "{job_id}"

    default_ttl_offset: ClassVar[int] = _DEFAULT_TTL_OFFSET

    user_id: str
    job_id: str
    status: str
    response: Optional[str] = None
    ttl: Optional[int] = None

    @classmethod
    def make_ttl(cls, offset_seconds: int = None) -> int:
        offset = (
            offset_seconds if offset_seconds is not None else cls.default_ttl_offset
        )
        return int(time.time()) + offset


class WorkerEvent(DBItem, BaseModel):
    """model worker events show when models start, stop, error etc"""

    pk_pattern: ClassVar[str] = "WORKER#{model_hash}"
    sk_pattern: ClassVar[str] = "EVENT#{event_type}#{timestamp}"

    model_hash: str
    model_name: str
    model_type: str
    event_type: str
    timestamp: str
    payload: dict = {}
    ttl: Optional[int] = None

    @classmethod
    def from_lifecycle_event(cls, evt: LifecycleEvent) -> "WorkerEvent":
        return cls(
            model_hash=evt.model_hash,
            model_name=evt.model_name,
            model_type=evt.payload.get("model_type", ""),
            event_type=evt.event_type,
            timestamp=evt.timestamp,
            payload=evt.payload,
            ttl=ResultsItem.make_ttl(),
        )


class InstanceEvent(DBItem, BaseModel):
    """instance events show cpu/gpu machines starting and stopping"""

    pk_pattern: ClassVar[str] = "INSTANCE#{instance_id}"
    sk_pattern: ClassVar[str] = "EVENT#{event_type}#{timestamp}"

    instance_id: str
    instance_type: str
    event_type: str
    timestamp: str
    spot: bool = False
    payload: dict = {}
    ttl: Optional[int] = None

    @classmethod
    def from_lifecycle_event(cls, evt: LifecycleEvent) -> "InstanceEvent":
        return cls(
            instance_id=evt.payload.get("instance_id", ""),
            instance_type=evt.payload.get("instance_type", ""),
            event_type=evt.event_type,
            timestamp=evt.timestamp,
            spot=evt.payload.get("spot", False),
            payload=evt.payload,
            ttl=ResultsItem.make_ttl(),
        )


class ModelCatalogueItem(DBItem, BaseModel):
    """One entry in the model catalogue.

    Sourced from models-*.yaml at init time; hash and queue_name are
    derived, not stored input -- never set them directly, they are
    fixed by model_name and model_type.
    """

    pk_pattern: ClassVar[str] = "MODEL#{type}"
    sk_pattern: ClassVar[str] = "MODELNAME#{name}"

    name: str
    type: ModelType
    provider: ModelProvider
    input: str
    output: str
    timeout: int = 180
    memory_size: int = 2048
    extra_env: dict = {}
    description: str = ""
    source_file: str = ""
    active: bool = True
    updated_at: Optional[str] = None  # set by the init step, not by the loader

    @computed_field
    @property
    def hash(self) -> str:
        """md5(model_name#model_type) -- the compound key, replacing md5(name)."""
        return _md5(f"{self.name}#{self.type.value}".encode()).hexdigest()

    @computed_field
    @property
    def queue_name(self) -> str:
        return f"mdl_{self.hash}_queue"
