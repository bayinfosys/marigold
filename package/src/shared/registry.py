"""Model registry.

Defines OutputField, ModelSpec, the @model_spec decorator, and
BaseModelHandler. Handler modules import from here to register themselves.

_SPECS is the singleton registry. Python's import machinery ensures this
module is initialised once regardless of how many times it is imported.
"""
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from time import perf_counter as clock
from typing import Any, Callable, Dict, List, Optional, Type

from shared.enums import ModelMode, ModelType, OutputMimeType
from shared.outputs import write_binary_output

import logging

logger = logging.getLogger(__name__)


@dataclass
class OutputField:
    """Declares one output produced by a model handler.

    name      -- field identifier, used in S3 key and API retrieval path
    mimetype  -- determines storage backend via OutputMimeType.storage
    writer    -- override the default writer for this field; None uses the
                 default derived from mimetype (write_binary_output for S3,
                 write_json_output for DynamoDB)
    """

    name: str
    mimetype: OutputMimeType
    writer: Optional[Callable] = None


@dataclass
class ModelSpec:
    """Complete definition of a model type.

    Registered by the @model_spec decorator on the handler class.
    Couples the enum value, mode, loader, handler class, request/response
    schemas, output fields, and API route path without requiring any of
    them to be defined together.
    """

    model_type: ModelType
    mode: ModelMode
    output_fields: List[OutputField]
    handler_class: Type
    loader: Callable
    request_model: Type
    response_model: Type
    route: str


# Maps ModelType.value -> ModelSpec.
# Populated at import time by @model_spec decorators in handler modules.
_SPECS: Dict[str, ModelSpec] = {}


def model_spec(
    model_type: ModelType,
    mode: ModelMode,
    output_fields: List[OutputField],
    loader: Callable,
    request_model: Type,
    response_model: Type,
    route: str,
):
    """Decorator that registers a handler class as the implementation of a model type.

    Raises ValueError at import time if the same ModelType is registered twice,
    catching copy-paste errors before they reach runtime.

    Usage::

        @model_spec(
            model_type=ModelType.TEXT_EVAL,
            mode=ModelMode.EVAL,
            output_fields=[],
            loader=load_text_eval,
            request_model=EvalTextRequest,
            response_model=EvalResponse,
            route="/eval/text",
        )
        class TextEvalModel(BaseModelHandler):
            ...
    """

    def decorator(cls):
        key = model_type.value
        if key in _SPECS:
            raise ValueError(
                "ModelType '%s' is already registered by %s"
                % (key, _SPECS[key].handler_class.__name__)
            )
        cls._model_type = model_type
        _SPECS[key] = ModelSpec(
            model_type=model_type,
            mode=mode,
            output_fields=output_fields,
            handler_class=cls,
            loader=loader,
            request_model=request_model,
            response_model=response_model,
            route=route,
        )
        return cls

    return decorator


class BaseModelHandler(ABC):
    """Base class for all model handlers.

    Subclasses must implement _run(). The SQSWorker calls process() with
    the raw request dict from the SQS message body and expects a Pydantic
    BaseModel instance in return.

    process() validates the raw request dict against the ModelSpec's
    request_model and passes the typed result to _run(). Subclasses do not
    override process().

    Model loading (from EFS cache) happens in __init__ so it occurs once
    at task start, not per message. The loader is called via the ModelSpec
    registered by @model_spec and must return a ModelLoaderResult.

    self.processor and self.model are set from the ModelLoaderResult.
    processor is None for loaders that use sentence-transformers or return
    a single pipeline object. Subclasses that need a named alias
    (e.g. self.pipe) assign it after calling super().__init__().
    """

    def __init__(self, modelname: str):
        self.modelname = modelname
        cache_dir = os.getenv("CACHE_DIR", "/mnt/efs/cache")
        spec = _SPECS[self._model_type.value]  # set by decorator
        T = clock()
        result = spec.loader(self.modelname, cache_dir)
        self.processor = result.processor
        self.model = result.model
        logger.info("'%s' loaded in %0.2fs", modelname, clock() - T)

    def write_output(self, field_name: str, data: bytes, message_id: str):
        """Write a binary output field to S3 and return an OutputReference.

        Looks up the field's mimetype from the ModelSpec output_fields
        declaration. Raises ValueError if field_name is not declared.

        Handlers with binary outputs call this instead of write_binary_output
        directly, removing the need to import or reference OUTPUT_BUCKET.
        """
        spec = _SPECS[self._model_type.value]
        field = next(
            (f for f in spec.output_fields if f.name == field_name), None
        )
        if field is None:
            raise ValueError(
                "output field '%s' not declared in ModelSpec for '%s'"
                % (field_name, spec.model_type.value)
            )
        bucket = os.environ["OUTPUT_BUCKET"]
        return write_binary_output(
            message_id=message_id,
            model_type=self._model_type,
            field_name=field_name,
            data=data,
            mimetype=field.mimetype.value,
            bucket=bucket,
        )

    def process(self, user_id: str, message_id: str, request: dict) -> Any:
        """Validate the raw request dict and dispatch to _run().

        Called by SQSWorker for every message. Not overridden by subclasses.
        Validation errors from model_validate propagate as-is; the SQSWorker
        catches all exceptions and writes an error status to DynamoDB.
        """
        spec = _SPECS[self._model_type.value]
        validated = spec.request_model.model_validate(request)
        return self._run(user_id, message_id, validated)

    @abstractmethod
    def _run(self, user_id: str, message_id: str, request: Any) -> Any:
        """Run one inference pass and return a Pydantic response model instance.

        user_id    -- authenticated caller identifier, used for logging and
                      usage recording
        message_id -- unique identifier for this job, used for logging and
                      as the S3 key component for binary outputs
        request    -- validated request model instance, typed to the specific
                      request class declared in the ModelSpec
        """
