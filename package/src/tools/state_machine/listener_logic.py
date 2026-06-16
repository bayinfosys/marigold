"""Local state listener -- Postgres NOTIFY equivalent of state_listener.py.

On AWS, state_listener.handler() is invoked by SNS for each lifecycle event
and writes state transitions to DynamoDB.

The STATE_MAP and event handling logic mirrors state_listener.py exactly.
The only difference is the backend injected -- DynamoDB on AWS, Postgres
locally -- and the delivery mechanism.
"""

import json
import logging
import threading

from shared.db_models import ResultsItem
from shared.sns_models import EventType, LifecycleEvent

logger = logging.getLogger(__name__)

STATE_MAP = {
    EventType.REQUEST_QUEUED: "queued",
    EventType.WORKER_LAUNCHING: "provisioning",
    EventType.MODEL_LOADING: "provisioning",
    EventType.MODEL_LOADED: "provisioning",
    EventType.REQUEST_DEQUEUED: "processing",
    EventType.REQUEST_PROCESSING: "processing",
    EventType.REQUEST_COMPLETE: "complete",
    EventType.REQUEST_ERROR: "error",
    EventType.MODEL_LOAD_FAILED: "error",
}

# Events with no message_id -- not written to the results table.
WORKER_EVENTS = {
    EventType.WORKER_STARTED,
    EventType.WORKER_IDLE,
    EventType.WORKER_EXITING,
}

INSTANCE_EVENTS = {
    EventType.INSTANCE_START,
    EventType.INSTANCE_TERMINATE,
}
