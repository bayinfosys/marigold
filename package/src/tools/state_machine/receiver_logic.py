import logging
from hashlib import md5

from backend.messaging.base import NotificationBackend, QueueBackend
from dynawrap.backends.postgres import PostgresBackend
from models.catalogue import get_model
from shared.enums import ModelType
from shared.schedule_models import MarigoldMessage, EventType, LifecycleEvent
from tools.polling.results_cache import ResultsCache

logger = logging.getLogger(__name__)


def handle_submission(
    user_id: str,
    body: dict,
    model_type: ModelType,
    catalogue_backend: PostgresBackend,
    catalogue_table: str,
    queue_backend: QueueBackend,
    notification_backend: NotificationBackend,
    results_cache: ResultsCache,
    topic: str,
) -> tuple[int, dict]:
    """Validate, deduplicate, and enqueue a model request.

    model_type comes from the route that was called (/gen/instruct fixes
    it to ModelType.INSTRUCT before this function ever runs) -- it is not
    derived from model_name, since the catalogue key is (model_type,
    model_name) together, not name alone.

    TODO: define a pydantic object for response
    """
    model_name = body.get("model")
    if not model_name:
        return 400, {"status": "error", "message": "model field required"}

    model_name = model_name.lower()
    body_hash = md5(str(body).encode()).hexdigest()
    message_id = "API#" + body_hash

    existing = results_cache.get_status(user_id, message_id)
    if existing:
        logger.info("[%s/%s] cache hit status=%s", user_id, message_id, existing)
        return 200, {"message_id": body_hash, "status": existing}

    model = get_model(catalogue_backend, catalogue_table, model_type, model_name)
    if model is None:
        logger.warning("[%s] unknown model: '%s' (%s)", user_id, model_name, model_type)
        return 400, {"status": "error", "message": "unknown model"}

    results_cache.create(user_id, message_id, status="queued")
    logger.info("[%s/%s] queued for model '%s'", user_id, message_id, model_name)

    msg = MarigoldMessage(
        user_id=user_id,
        message_id=message_id,
        model_type=model.type,
        model_name=model_name,
        model_inputs=body,
    )

    logger.info("[%s/%s] submitting %s to %s", user_id, message_id, msg.model_dump_json()[:200], model.queue_name)

    try:
        queue_backend.send(model.queue_name, msg.model_dump(), message_id=message_id)
    except Exception as e:
        logger.exception("[%s/%s] failed to enqueue: %s", user_id, message_id, e)
        results_cache.update_status(user_id, message_id, "error")
        return 500, {"status": "error", "message": "internal error"}

    try:
        event = LifecycleEvent(
            event_type=EventType.REQUEST_QUEUED,
            model_name=model_name,
            model_hash=model.hash,
            message_id=message_id,
            payload={"user_id": user_id, "model_type": model.type},
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
    """Get the status of a message from the cache

    TODO: define a pydantic object for this response
    """
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
    """Delete a message from the cache
    """
    full_id = "API#" + message_id
    results_cache.delete(user_id, full_id)
    return 200, {"status": "ok", "message": "deleted", "message_id": message_id}
