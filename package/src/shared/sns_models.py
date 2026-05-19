"""SNS lifecycle event models for the Marigold state machine.

Published by: request_receiver, task_runner, worker
Consumed by:  task_runner, state_listener
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import boto3
from pydantic import BaseModel

logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))

_sns = None


def _get_sns():
    global _sns
    if _sns is None:
        _sns = boto3.client("sns")
    return _sns


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
        topic_arn = os.environ.get("LIFECYCLE_TOPIC_ARN")
        if not topic_arn:
            return
        try:
            _get_sns().publish(**self.to_sns_kwargs(topic_arn))
        except Exception as e:
            logger.warning("failed to publish %s: %s", self.event_type, e)

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
