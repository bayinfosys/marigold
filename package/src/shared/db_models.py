"""
shared/db_models.py -- item definitions for the platform's tables.

PK/SK patterns are the authoritative source for all key construction.
Values are sourced from CONTRACTS.md. No key strings are constructed
anywhere outside this module.

Items are persisted through a dynawrap backend: Postgres on the platform.
"""
import os
import time
from hashlib import md5 as _md5
from typing import ClassVar, Optional

from dynawrap import DBItem
from pydantic import BaseModel, Field, computed_field

from .schedule_models import LifecycleEvent
from .enums import ModelType, ModelProvider, StatusCode
from .model_settings import ModelSettings


_DEFAULT_TTL_OFFSET = 86400 * 30  # 30 days


# The loader settings, as environment variables.
_ENV_KEYS = tuple(name.upper() for name in ModelSettings.model_fields)

# The keys the last call to set_model_config_env set. The next call
# clears them, so a handler setting such as NUM_STEPS applies to the
# model that declares it and to no other.
_applied_keys: set[str] = set()


def set_model_config_env(settings: ModelSettings) -> None:
    """Apply model settings to the process environment.

    Each set setting becomes its name upper-cased, booleans as "true" or
    "false" and other values as strings. Clears the loader keys and
    every key the previous call set first. Shared between worker.py
    (serve time) and model_cache_shared.py (cache-init time) so both
    load a model under the same settings.
    """
    for key in (*_ENV_KEYS, *_applied_keys):
        os.environ.pop(key, None)

    _applied_keys.clear()

    for name, value in settings.model_dump(exclude_none=True).items():
        key = name.upper()
        os.environ[key] = str(value).lower() if isinstance(value, bool) else str(value)
        _applied_keys.add(key)


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
    code: StatusCode = StatusCode.OK
    response: Optional[str] = None
    ttl: Optional[int] = None

    @classmethod
    def make_ttl(cls, offset_seconds: int = None) -> int:
        offset = (
            offset_seconds if offset_seconds is not None else cls.default_ttl_offset
        )
        return int(time.time()) + offset


class WorkerEnvironment(DBItem, BaseModel):
    """What a worker node is and what it is running on.

    Written once at worker startup, append-only: a restart writes a new
    record rather than updating, so an inference resolves to the
    environment that actually ran it. started_at is the sort key, so
    records for one worker come back in chronological order.

    started_at is an ISO-8601 UTC string rather than a datetime because
    sort keys compare lexicographically, and a fixed-width ISO string is
    the only format where that ordering is also chronological. Matches
    WorkerEvent.timestamp and InstanceEvent.timestamp.

    No TTL. A usage row from six months ago resolving to a deleted
    environment record loses the provenance this table exists to
    provide.
    """

    pk_pattern: ClassVar[str] = "WORKERENV#{worker_id}"
    sk_pattern: ClassVar[str] = "ENVIRONMENT#{started_at}"

    worker_id:  str = Field(..., description="stable node name: MARIGOLD_WORKER_ID, or hostname")
    hostname:   str = Field(..., description="what the process reports; a container id unless compose sets it")
    started_at: str = Field(..., description="ISO-8601 UTC, sortable")

    marigold_version:     str = ""
    torch_version:        str = ""
    diffusers_version:    str = ""
    transformers_version: str = ""

    cuda_available:      bool = False
    cuda_version:        str = ""
    driver_version:      str = ""
    device_count:        int = 0
    device_names:        list[str] = Field(default_factory=list)
    device_memory_bytes: list[int] = Field(default_factory=list)


class WorkerEvent(DBItem, BaseModel):
    """One lifecycle event for one model: a request, a load, the worker.

    Keyed by model, sorted by timestamp then event type, so a query on
    one model returns its history in time order, and reversed, newest
    first. timestamp is ISO-8601 UTC for the same reason as
    WorkerEnvironment.started_at.

    No TTL: rows accumulate, so a model's history survives restarts and
    log rotation.
    """

    pk_pattern: ClassVar[str] = "WORKER#{model_hash}"
    sk_pattern: ClassVar[str] = "EVENT#{timestamp}#{event_type}"

    model_hash: str
    model_name: str
    model_type: str
    event_type: str
    timestamp: str
    message_id: Optional[str] = None
    payload: dict = {}

    @classmethod
    def from_lifecycle_event(cls, evt: LifecycleEvent) -> "WorkerEvent":
        return cls(
            model_hash=evt.model_hash,
            model_name=evt.model_name,
            model_type=str(evt.payload.get("model_type", "")),
            event_type=evt.event_type,
            timestamp=evt.timestamp,
            message_id=evt.message_id,
            payload=evt.payload,
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
    settings: ModelSettings = Field(default_factory=ModelSettings)
    description: str = ""
    source_file: str = ""
    failed_reason: Optional[str] = None
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

    @property
    def failed(self) -> bool:
        """A worker has attempted this model and the load failed.

        Runtime state, written by the worker. Absent from models.yaml and
        carried across a reconcile unchanged.
        """
        return self.failed_reason is not None
