"""Task queue -- SNS-triggered Lambda.

Receives REQUEST_QUEUED lifecycle events from the lifecycle SNS topic.
Decides how many additional workers are needed for the model and enqueues
that many launch requests onto the launch FIFO queue.

NB: this step **never** blocks from putting an task launch on the queue.
"""

import json
import logging
import os

import boto3
from shared.models import ModelDispatch
from shared.sns_models import EventType, LifecycleEvent

logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))

s3 = boto3.client("s3")
sns = boto3.client("sns")
sqs = boto3.client("sqs")
ecs = boto3.client("ecs")

CLUSTER_ARN = os.environ["ECS_CLUSTER_ARN"]
LIFECYCLE_TOPIC_ARN = os.environ.get("LIFECYCLE_TOPIC_ARN", "")
LAUNCH_QUEUE_URL = os.environ["LAUNCH_QUEUE_URL"]
DEFAULT_MAX_WORKERS = int(os.environ.get("DEFAULT_MAX_WORKERS", "4"))
LAUNCH_DEDUP_WINDOW = int(os.environ.get("LAUNCH_DEDUP_WINDOW_S", "30"))

_config: dict = {}


def load_model_config() -> dict:
    global _config
    if _config:
        return _config
    bucket = os.environ["AWS_S3_ASSETS_BUCKET_NAME"]
    key = os.environ["MODELS_CONFIG_S3_OBJECT"]
    obj = s3.get_object(Bucket=bucket, Key=key)
    data = json.loads(obj["Body"].read())
    _config = {name: ModelDispatch(**v) for name, v in data.items()}
    logger.info("loaded %d models", len(_config))
    return _config


def get_queue_depth(dispatch: ModelDispatch) -> int:
    attrs = sqs.get_queue_attributes(
        QueueUrl=dispatch.queue_url,
        AttributeNames=["ApproximateNumberOfMessages"],
    )["Attributes"]
    return int(attrs.get("ApproximateNumberOfMessages", 0))


def get_active_count(dispatch: ModelDispatch) -> int:
    resp = ecs.list_tasks(
        cluster=CLUSTER_ARN,
        desiredStatus="RUNNING",
        family=dispatch.family,
        maxResults=100,
    )
    return len(resp.get("taskArns", []))


def enqueue_launch(
    model_name: str,
    model_hash: str,
    message_id: str,
    slot: int,
) -> None:
    try:
        sqs.send_message(
            QueueUrl=LAUNCH_QUEUE_URL,
            MessageBody=json.dumps(
                {
                    "model_name": model_name,
                    "model_hash": model_hash,
                    "message_id": message_id,
                }
            ),
        )
        logger.info("model='%s' launch request enqueued slot=%d", model_name, slot)
    except Exception as e:
        logger.error("model='%s' failed to enqueue slot=%d: %s", model_name, slot, e)


def publish(evt: LifecycleEvent) -> None:
    if not LIFECYCLE_TOPIC_ARN:
        return
    try:
        sns.publish(**evt.to_sns_kwargs(LIFECYCLE_TOPIC_ARN))
    except Exception as e:
        logger.warning("failed to publish %s: %s", evt.event_type, e)


# ---------------------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------------------


ecs = boto3.client("ecs")

CLUSTER_ARN = os.environ["ECS_CLUSTER_ARN"]


def set_service_desired_count(
    dispatch: ModelDispatch, model_name: str, count: int
) -> None:
    ecs.update_service(
        cluster=CLUSTER_ARN,
        service=dispatch.service_name,
        desiredCount=count,
    )
    logger.info(
        "model='%s' service desired_count set to %d",
        model_name,
        count,
    )


def handle_request_queued(model_name: str, model_hash: str, message_id: str) -> None:
    logger.info("REQUEST_QUEUED for '%s'", model_name)

    try:
        models = load_model_config()
        dispatch = models.get(model_hash)
    except Exception as e:
        logger.error("failed to load model config: %s", e)
        return

    if not dispatch:
        logger.error("unknown model hash: %s", model_hash)
        return

    max_workers = (
        dispatch.max_workers
        if dispatch.max_workers is not None
        else DEFAULT_MAX_WORKERS
    )

    depth = get_queue_depth(dispatch)
    needed = min(max_workers, max(1, depth // dispatch.msg_per_instance))

    logger.info(
        "model='%s' depth=%d needed=%d max_workers=%d",
        model_name,
        depth,
        needed,
        max_workers,
    )

    # Check current desired count -- skip if already at needed
    current = ecs.describe_services(
        cluster=CLUSTER_ARN,
        services=[dispatch.service_name],
    )["services"][0]["desiredCount"]

    if current >= needed:
        logger.info(
            "model='%s' desired=%d >= needed=%d -- no update",
            model_name,
            current,
            needed,
        )
        return

    try:
        set_service_desired_count(dispatch, model_name, needed)
    except Exception as e:
        logger.exception("failed to update service desired_count: %s", e)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def handler(event, context):
    for record in event.get("Records", []):
        try:
            outer = json.loads(record["body"])
            attributes = outer.get("MessageAttributes", {})
            event_type = attributes.get("event_type", {}).get("Value", "")
            model_name = attributes.get("model_name", {}).get("Value", "")
            model_hash = attributes.get("model_hash", {}).get("Value", "")
            body = json.loads(outer["Message"])
            message_id = body.get("message_id", "")
        except Exception as e:
            logger.error("failed to parse record: %s", e)
            continue

        if event_type != EventType.REQUEST_QUEUED:
            logger.debug("no handler for event type '%s' -- skipping", event_type)
            continue

        try:
            handle_request_queued(model_name, model_hash, message_id)
        except Exception as e:
            logger.exception("handle_request_queued raised: %s", e)
