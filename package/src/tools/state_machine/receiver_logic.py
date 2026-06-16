import logging
from hashlib import md5

from backend.messaging.base import NotificationBackend, QueueBackend
from shared.sns_models import EventType
from shared.sqs_models import MarigoldSQSMessage
from tools.polling.results_cache import ResultsCache
from models.entrypoint_handlers import _queue_name

logger = logging.getLogger(__name__)


def handle_submission(
    user_id: str,
    body: dict,
    models_config: dict,
    queue_backend: QueueBackend,
    notification_backend: NotificationBackend,
    results_cache: ResultsCache,
    topic: str,
) -> tuple[int, dict]:
    """Validate, deduplicate, and enqueue a model request.

    Returns (http_status_code, response_dict). The caller renders
    the response in whatever format suits the transport (FastAPI,
    Lambda proxy, etc.).

    cache_state check is omitted for now -- to be added when a local
    cache_state source is available.
    """
    model_name = body.get("model")
    if not model_name:
        return 400, {"status": "error", "message": "model field required"}

    model_name = model_name.lower()
    model_hash = md5(model_name.encode()).hexdigest()
    body_hash = md5(str(body).encode()).hexdigest()
    message_id = "API#" + body_hash

    # Deduplication
    existing = results_cache.get_status(user_id, message_id)
    if existing:
        logger.info("[%s/%s] cache hit status=%s", user_id, message_id, existing)
        return 200, {"message_id": body_hash, "status": existing}

    # Model lookup
    dispatch = models_config.get(model_hash)

    if dispatch is None:
        logger.warning("[%s] unknown model: '%s'", user_id, model_name)
        return 400, {"status": "error", "message": "unknown model"}

    # Write initial status
    results_cache.create(user_id, message_id, status="queued")
    logger.info("[%s/%s] queued for model '%s'", user_id, message_id, model_name)

    # Construct and enqueue message
    msg = MarigoldSQSMessage(
        user_id=user_id,
        message_id=message_id,
        model_type=dispatch["type"],
        model_name=model_name,
        model_inputs=body,
    )

    queue_name = dispatch.get("queue_name") or _queue_name(model_hash)
    logger.info("[%s/%s] submitting %s to %s", user_id, message_id, msg.model_dump_json(), queue_name)

    try:
        queue_backend.send(queue_name, msg.model_dump(), message_id=message_id)
    except Exception as e:
        logger.exception("[%s/%s] failed to enqueue: %s", user_id, message_id, e)
        results_cache.update_status(user_id, message_id, "error")
        return 500, {"status": "error", "message": "internal error"}

    # Publish lifecycle event
    try:
        from shared.sns_models import LifecycleEvent
        event = LifecycleEvent(
            event_type=EventType.REQUEST_QUEUED,
            model_name=model_name,
            model_hash=model_hash,
            message_id=message_id,
            payload={"user_id": user_id, "model_type": dispatch["type"]},
        )
        notification_backend.publish(topic, event.model_dump())
    except Exception as e:
        logger.warning("[%s/%s] failed to publish lifecycle event: %s", user_id, message_id, e)

    return 200, {"message_id": body_hash}


def handle_status(
    user_id: str,
    message_id: str,
    results_cache: ResultsCache,
) -> tuple[int, dict]:
    full_id = "API#" + message_id
    status = results_cache.get_status(user_id, full_id)

    if status in ("complete", "error"):
        result = results_cache.get_response(user_id, full_id)
        return 200, {"status": status, "message_id": message_id, "result": result}
    elif status:
        return 202, {"status": status, "message_id": message_id}
    else:
        return 404, {"status": "not found", "message_id": message_id}


def handle_delete(
    user_id: str,
    message_id: str,
    results_cache: ResultsCache,
) -> tuple[int, dict]:
    full_id = "API#" + message_id
    results_cache.delete(user_id, full_id)
    return 200, {"status": "ok", "message": "deleted", "message_id": message_id}
