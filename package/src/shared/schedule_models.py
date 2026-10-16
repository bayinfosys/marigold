"""
shared/schedule_models.py -- Marigold messaging contract.

Defines the message shape for every Marigold model queue, and the
lifecycle events the worker and the API publish.

Used by:
  - api submission (message construction)
  - models/worker.py (message parsing)
  - models/standard_loader.py (lifecycle events)

Top-level fields are Marigold routing and observability metadata.
model_inputs is the payload passed verbatim to the model handler.
"""
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from pydantic import BaseModel


logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))


class MarigoldMessage(BaseModel):
    """
    Queue message body for every Marigold model queue.

    Top-level fields are consumed by Marigold infrastructure: routing,
    logging and result storage.

    model_inputs is opaque to Marigold -- it is passed verbatim to the
    model handler. Keys and value types are model-specific.
    """

    user_id: str
    message_id: str
    model_type: str
    model_name: str
    model_inputs: Dict[str, Any]


def make_job_id(message: MarigoldMessage) -> str:
    """The results cache key for a message: its message_id, which is
    already a hash of the request and unique per distinct request."""
    return message.message_id


class EventType:
    REQUEST_QUEUED = "REQUEST_QUEUED"
    REQUEST_DEQUEUED = "REQUEST_DEQUEUED"
    WORKER_LAUNCHING = "WORKER_LAUNCHING"
    WORKER_STARTED = "WORKER_STARTED"
    MODEL_LOADING = "MODEL_LOADING"
    MODEL_LOADED = "MODEL_LOADED"
    MODEL_LOAD_FAILED = "MODEL_LOAD_FAILED"
    REQUEST_PROCESSING = "REQUEST_PROCESSING"
    REQUEST_COMPLETE = "REQUEST_COMPLETE"
    REQUEST_ERROR = "REQUEST_ERROR"
    WORKER_IDLE = "WORKER_IDLE"
    WORKER_EXITING = "WORKER_EXITING"
    INSTANCE_START = "INSTANCE_START"
    INSTANCE_TERMINATE = "INSTANCE_TERMINATE"


class LifecycleEvent(BaseModel):
    """A lifecycle event: a request, model or worker changing state.

    Published by the API's submission path and the worker, through a
    NotificationBackend; locally, LocalNotificationBackend logs them.
    """
    event_type: str
    model_name: str
    model_hash: str
    message_id: Optional[str] = None
    timestamp: str = ""
    payload: dict = {}

    def model_post_init(self, __context):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def post(self) -> None:
        raise NotImplementedError("LIFECYCLE_TOPICS unavailable")
