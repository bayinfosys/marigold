"""SNS lifecycle event models for the Marigold state machine.

Published by: request_receiver, task_runner, worker
Consumed by:  task_runner, state_listener
"""
import json
from datetime import datetime, timezone
from typing   import Optional

from pydantic import BaseModel


class EventType:
    REQUEST_QUEUED     = "REQUEST_QUEUED"
    WORKER_LAUNCHING   = "WORKER_LAUNCHING"
    WORKER_STARTED     = "WORKER_STARTED"
    MODEL_LOADING      = "MODEL_LOADING"
    MODEL_LOADED       = "MODEL_LOADED"
    MODEL_LOAD_FAILED  = "MODEL_LOAD_FAILED"
    REQUEST_PROCESSING = "REQUEST_PROCESSING"
    REQUEST_COMPLETE   = "REQUEST_COMPLETE"
    REQUEST_ERROR      = "REQUEST_ERROR"
    WORKER_IDLE        = "WORKER_IDLE"
    WORKER_EXITING     = "WORKER_EXITING"


class LifecycleEvent(BaseModel):
    event_type: str
    model_name: str
    model_hash: str
    message_id: Optional[str] = None
    timestamp:  str           = ""
    payload:    dict          = {}

    def model_post_init(self, __context):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_sns_kwargs(self, topic_arn: str) -> dict:
        return {
            "TopicArn": topic_arn,
            "Message":  self.model_dump_json(),
            "MessageAttributes": {
                "event_type": {
                    "DataType":    "String",
                    "StringValue": self.event_type,
                },
                "model_hash": {
                    "DataType":    "String",
                    "StringValue": self.model_hash,
                },
            },
        }

    @classmethod
    def from_sns_record(cls, record: dict) -> "LifecycleEvent":
        return cls.model_validate(json.loads(record["Sns"]["Message"]))
