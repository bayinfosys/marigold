"""
shared/schedule_models.py -- Marigold messaging contract.

Defines the canonical message shape for all Marigold queues.

Used by:
  - tools/workflow/runner.py      (dispatch, message construction)
  - tools/workflow/model_dummy.py (worker, message parsing)
  - package/src/models/*.py       (ECS workers, message parsing)
  - tools/polling/ecs.py          (direct API path, message construction)

Top-level fields are Marigold routing and observability metadata.
model_inputs is the payload passed verbatim to the model handler.
"""
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from pydantic import BaseModel

from hashlib import md5 as _md5


logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))


class MarigoldMessage(BaseModel):
    """
    Canonical SQS message body for all Marigold model queues.

    Top-level fields are consumed by Marigold infrastructure:
    routing, logging, result storage, workflow state advancement.

    model_inputs is opaque to Marigold -- it is passed verbatim to
    the model handler. Keys and value types are model-specific.
    """

    user_id: str
    message_id: str
    model_type: str
    model_name: str
    model_inputs: Dict[str, Any]

    # Workflow fields -- null for direct API requests
    workflow_execution_id: Optional[str] = None
    op: Optional[str] = None
    run_id: Optional[int] = None


def make_job_id(message: MarigoldMessage) -> str:
    """Derive a stable unique job_id for a results cache record.

    For direct API jobs (no workflow_execution_id):
        the message_id is already unique -- returned as-is.

    For workflow step jobs:
        md5 of workflow_execution_id#op#run_id. The inclusion of run_id
        means retries produce distinct job_ids. Fixed-length regardless
        of component length.
    """
    if message.workflow_execution_id is None:
        return message.message_id
    key = f"{message.workflow_execution_id}#{message.op}#{message.run_id}"
    return _md5(key.encode()).hexdigest()


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
    """lifecycle event models for the Marigold state machine.

    Published by: request_receiver, task_runner, worker
    Consumed by:  task_runner, state_listener
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

    def to_sns_kwargs(self, topic_arn: str) -> dict:
        return {
            "TopicArn": topic_arn,
            "Message": self.model_dump_json(),
            "MessageAttributes": {
                "event_type": {
                    "DataType": "String",
                    "StringValue": self.event_type,
                },
                "model_hash": {
                    "DataType": "String",
                    "StringValue": self.model_hash,
                },
            },
        }

    @classmethod
    def from_sns_record(cls, record: dict) -> "LifecycleEvent":
        return cls.model_validate(json.loads(record["Sns"]["Message"]))
