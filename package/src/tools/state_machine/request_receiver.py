"""Request receiver -- API Gateway entry point.

Validates the request, writes PENDING status to results cache,
publishes REQUEST_QUEUED to the lifecycle SNS topic.

SNS fan-out delivers to:
  - the per-model SQS queue (SNS->SQS subscription, filtered on model_name)
  - task_runner Lambda  (SNS->Lambda subscription, filtered on event_type)
"""

import json
import logging
import os
from hashlib import md5

import boto3
from shared.lambda_proxy import get_userid_from_event, mk_resp
from shared.models import ModelDispatch
from shared.sns_models import EventType
from shared.sqs_models import MarigoldSQSMessage
from tools.polling.cache import (create_status, delete_cache, get_response,
                                 get_status)
from tools.polling.chathack import handle_chat_submission

logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))

s3 = boto3.client("s3")
sns = boto3.client("sns")

LIFECYCLE_TOPIC_ARN = os.environ.get("LIFECYCLE_TOPIC_ARN", "")

_config: dict = {}
_cache_state: dict = {}


def load_model_config() -> dict:
    global _config
    if _config:
        return _config
    bucket = os.environ["AWS_S3_ASSETS_BUCKET_NAME"]
    key = os.environ["MODELS_CONFIG_S3_OBJECT"]
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
        data = json.loads(obj["Body"].read())
        _config = {name: ModelDispatch(**v) for name, v in data.items()}
        logger.info("loaded %d models", len(_config))
    except Exception as e:
        logger.exception("failed to load model config: %s", e)
        raise
    return _config


def load_cache_state() -> dict:
    global _cache_state
    if _cache_state:
        return _cache_state
    bucket = os.environ["AWS_S3_ASSETS_BUCKET_NAME"]
    key = os.environ.get("CACHE_STATE_S3_OBJECT", "cache_state.json")
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
        data = json.loads(obj["Body"].read())
        _cache_state = data.get("models", {})
        logger.info("loaded cache state for %d models", len(_cache_state))
    except Exception as e:
        logger.critical("failed to load cache state: %s", e)
    return _cache_state


load_model_config()
load_cache_state()
assert _config, "unable to load MODELS_CONFIG"


def handler(event, context):
    logger.info("request_receiver version=%s", os.getenv("BUILD_VERSION", "unknown"))
    logger.debug("event: %s", str(event))

    method = event["httpMethod"]
    user_id = get_userid_from_event(event)

    dispatch_map = {
        "POST": handle_submission,
        "GET": handle_status,
        "DELETE": delete_status,
        "OPTIONS": lambda u, e: mk_resp(200, {}),
    }

    try:
        return dispatch_map[method](user_id, event)
    except KeyError as e:
        logger.warning("method not found: %s", e)
        return mk_resp(405, {"status": "error", "message": "method not allowed"})
    except Exception as e:
        logger.exception("error in handler: %s", e)
        return mk_resp(500, {"status": "error", "message": "internal error"})


def handle_submission(user_id, event):
    body = event["body"]
    body_md5 = md5(body.encode("utf-8")).hexdigest()
    message_id = "API#" + body_md5
    path = event.get("path", "")

    if path.startswith("/demo/chat"):
        return handle_chat_submission(user_id, event)

    logger.info("[%s/%s]", user_id, message_id)

    message_content = json.loads(body)
    model_name = message_content.get("model")

    if not model_name:
        return mk_resp(400, {"status": "error", "message": "model field required"})

    model_name = model_name.lower()
    model_name_md5 = md5(model_name.encode()).hexdigest()

    # Deduplication
    existing_status = get_status(user_id, message_id)
    if existing_status:
        logger.info("[%s/%s] cache hit status=%s", user_id, message_id, existing_status)
        return mk_resp(200, {"message_id": body_md5, "status": existing_status})

    # Model config lookup
    models = load_model_config()
    try:
        dispatch = models[model_name_md5]
    except KeyError:
        logger.warning("[%s] unknown model: '%s'", user_id, model_name)
        return mk_resp(400, {"status": "error", "message": "unknown model"})

    # Cache state check
    cache_state = load_cache_state()
    if not cache_state:
        logger.critical("[%s] cache state unavailable", user_id)
        return mk_resp(503, {"status": "error", "message": "service_unavailable"})

    model_cache = cache_state.get(model_name)
    if not model_cache:
        logger.critical("[%s] model not in cache state: '%s'", user_id, model_name)
        return mk_resp(
            400,
            {"status": "error", "message": "model_not_available", "model": model_name},
        )

    if model_cache.get("status") != "ok":
        logger.critical(
            "[%s] model cache status not ok: '%s' status=%s",
            user_id,
            model_name,
            model_cache.get("status"),
        )
        return mk_resp(
            400,
            {
                "status": "error",
                "message": "model_not_available",
                "model": model_name,
                "cache_status": model_cache.get("status"),
            },
        )

    # Write queued status
    create_status(user_id, message_id, status="queued")
    logger.info("[%s/%s] queued for model '%s'", user_id, message_id, model_name)

    # Write to SQS
    msg = MarigoldSQSMessage(
        user_id=user_id,
        message_id=message_id,
        model_type=dispatch.model_type,
        model_name=model_name,
        model_inputs=message_content,
    )

    try:
        sns.publish(
            TopicArn=LIFECYCLE_TOPIC_ARN,
            Message=msg.model_dump_json(),
            MessageAttributes={
                "event_type": {
                    "DataType": "String",
                    "StringValue": EventType.REQUEST_QUEUED,
                },
                "model_name": {
                    "DataType": "String",
                    "StringValue": model_name,
                },
                "model_hash": {
                    "DataType": "String",
                    "StringValue": model_name_md5,
                },
            },
        )
    except Exception as e:
        logger.critical("[%s/%s] SNS publish failed: %s", user_id, message_id, e)
        return mk_resp(500, {"status": "error", "message": "internal error"})

    return mk_resp(200, {"message_id": body_md5})


def handle_status(user_id, event):
    raw_id = event["pathParameters"]["message_id"]
    message_id = "API#" + raw_id
    status = get_status(user_id, message_id)

    if status in ("complete", "error"):
        result = get_response(user_id, message_id)
        return mk_resp(200, {"status": status, "message_id": raw_id, "result": result})
    elif status:
        return mk_resp(202, {"status": status, "message_id": raw_id})
    else:
        return mk_resp(404, {"status": "not found", "message_id": raw_id})


def delete_status(user_id, event):
    raw_id = event["pathParameters"]["message_id"]
    message_id = "API#" + raw_id
    delete_cache(user_id, message_id)
    return mk_resp(200, {"status": "ok", "message": "deleted", "message_id": raw_id})
