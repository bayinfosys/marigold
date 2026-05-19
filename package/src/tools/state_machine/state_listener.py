"""State listener -- SNS-triggered Lambda.

Receives lifecycle events and writes state to DynamoDB.
Single source of truth for all state transitions.

Request-scoped events (have message_id):
    Handled by handle_request_event -- writes to results cache.

Infrastructure-scoped events (no message_id):
    Handled by handle_worker_event and handle_instance_event --
    writes to worker/instance tables (not yet implemented).
"""

import json
import logging
import os

import boto3
from dynawrap.backends.dynamodb import DynamoDBBackend

from shared.db_models import ResultsItem, WorkerEvent, InstanceEvent
from shared.sns_models import EventType, LifecycleEvent

logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))

_ddb = boto3.client("dynamodb")
_dynawrap = DynamoDBBackend(_ddb)

RESULTS_TABLE = os.environ["RESULTS_TABLE"]
WORKER_EVENTS_TABLE = os.environ["WORKER_EVENTS_TABLE"]
INSTANCE_EVENTS_TABLE = os.environ["INSTANCE_EVENTS_TABLE"]

# ---------------------------------------------------------------------------
# Request-scoped events
# ---------------------------------------------------------------------------

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

HINTS = {
    EventType.WORKER_LAUNCHING: "GPU instance starting",
    EventType.MODEL_LOADING: "model loading from cache",
    EventType.MODEL_LOADED: "model ready, processing shortly",
}

WORKER_EVENTS = {
    EventType.WORKER_STARTED,
    EventType.WORKER_IDLE,
    EventType.WORKER_EXITING,
}

INSTANCE_EVENTS = {
    EventType.INSTANCE_START,
    EventType.INSTANCE_TERMINATE,
}


def _get_item(user_id: str, message_id: str) -> ResultsItem | None:
    item = _dynawrap.get(
        RESULTS_TABLE,
        ResultsItem,
        user_id=user_id,
        job_id=message_id,
    )
    if item is None:
        logger.warning("[%s/%s] record not found", user_id, message_id)
    return item


def handle_request_event(evt: LifecycleEvent) -> None:
    status = STATE_MAP.get(evt.event_type)
    if not status:
        logger.debug("no state mapping for event type '%s' -- skipping", evt.event_type)
        return

    if not evt.message_id:
        return

    user_id = evt.payload.get("user_id")
    if not user_id:
        logger.warning(
            "[%s] no user_id in payload for %s", evt.message_id, evt.event_type
        )
        return

    item = _get_item(user_id, evt.message_id)
    if item is None:
        return

    hint = HINTS.get(evt.event_type)
    response = None

    if evt.event_type == EventType.REQUEST_COMPLETE:
        result = evt.payload.get("result")
        response = json.dumps(result) if result else None
    elif evt.event_type in (EventType.REQUEST_ERROR, EventType.MODEL_LOAD_FAILED):
        error = evt.payload.get("error")
        response = json.dumps({"error": error}) if error else None
    elif hint:
        response = json.dumps({"hint": hint})

    updated = item.model_copy(
        update={
            "status": status,
            "response": response if response is not None else item.response,
        }
    )

    try:
        _dynawrap.save(RESULTS_TABLE, updated)
        logger.info("[%s/%s] %s -> %s", user_id, evt.message_id, evt.event_type, status)
    except Exception as e:
        logger.error(
            "[%s/%s] failed to update status for %s: %s",
            user_id,
            evt.message_id,
            evt.event_type,
            e,
        )


# ---------------------------------------------------------------------------
# Worker-scoped events
# ---------------------------------------------------------------------------


def handle_worker_event(evt: LifecycleEvent) -> None:
    logger.info("WORKER_EVENT  type=%s  model=%s", evt.event_type, evt.model_name)
    item = WorkerEvent.from_lifecycle_event(evt)
    _dynawrap.save(WORKER_EVENTS_TABLE, item)


# ---------------------------------------------------------------------------
# Instance-scoped events
# ---------------------------------------------------------------------------


def handle_instance_event(evt: LifecycleEvent) -> None:
    item = InstanceEvent.from_lifecycle_event(evt)
    _dynawrap.save(INSTANCE_EVENTS_TABLE, item)
    logger.info(
        "INSTANCE_EVENT  type=%s  instance=%s",
        evt.event_type,
        evt.payload.get("instance_id"),
    )


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


def handler(event, context):
    for record in event.get("Records", []):
        try:
            evt = LifecycleEvent.from_sns_record(record)
        except Exception as e:
            logger.error("failed to parse SNS record: %s", e)
            continue

        if evt.event_type in WORKER_EVENTS:
            handle_worker_event(evt)
        elif evt.event_type in INSTANCE_EVENTS:
            handle_instance_event(evt)
        else:
            handle_request_event(evt)
