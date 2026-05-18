"""State listener -- SNS-triggered Lambda.

Receives lifecycle events and writes request state to DynamoDB.
Single source of truth for all state transitions.
"""

import logging
import os

import boto3
from shared.sns_models import EventType, LifecycleEvent
from tools.polling.cache import update_status

logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))

# Map event types to request statuses.
# Only events with a message_id produce state transitions.
STATE_MAP = {
    EventType.REQUEST_QUEUED: "queued",
    EventType.WORKER_LAUNCHING: "provisioning",
    EventType.MODEL_LOADING: "provisioning",
    EventType.MODEL_LOADED: "provisioning",
    EventType.REQUEST_PROCESSING: "submitted",
    EventType.REQUEST_COMPLETE: "complete",
    EventType.REQUEST_ERROR: "error",
    EventType.MODEL_LOAD_FAILED: "error",
}

# Hint text shown to polling clients during provisioning sub-states.
HINTS = {
    EventType.WORKER_LAUNCHING: "GPU instance starting",
    EventType.MODEL_LOADING: "model loading from cache",
    EventType.MODEL_LOADED: "model ready, processing shortly",
}


def handler(event, context):
    for record in event.get("Records", []):
        try:
            evt = LifecycleEvent.from_sns_record(record)
        except Exception as e:
            logger.error("failed to parse SNS record: %s", e)
            continue

        status = STATE_MAP.get(evt.event_type)
        if not status:
            continue

        if not evt.message_id:
            continue

        hint = HINTS.get(evt.event_type)
        payload = {"hint": hint} if hint else None

        try:
            update_status(evt.message_id, status, payload)
            logger.info(
                "[%s] %s -> %s",
                evt.message_id,
                evt.event_type,
                status,
            )
        except Exception as e:
            logger.error(
                "[%s] failed to update status for %s: %s",
                evt.message_id,
                evt.event_type,
                e,
            )
