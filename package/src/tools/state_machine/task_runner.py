"""Task runner -- SNS-triggered Lambda.

Receives lifecycle events from the lifecycle topic.
Currently handles REQUEST_QUEUED by launching an ECS task if none is active.
Publishes WORKER_LAUNCHING on successful launch.
"""

import json
import logging
import os
import uuid

import boto3
from shared.models import ModelDispatch
from shared.sns_models import EventType, LifecycleEvent

logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))

s3 = boto3.client("s3")
ecs = boto3.client("ecs")
sns = boto3.client("sns")
sqs = boto3.client("sqs")

LIFECYCLE_TOPIC_ARN = os.environ.get("LIFECYCLE_TOPIC_ARN", "")
CLUSTER_ARN = os.environ["ECS_CLUSTER_ARN"]
SUBNETS = os.environ["ECS_SUBNETS"].split(",")
SECURITY_GROUPS = os.environ["ECS_SECURITY_GROUPS"].split(",")
SCALE_THRESHOLD = int(os.environ.get("WORKER_SCALE_THRESHOLD", "10"))
MAX_WORKERS = int(os.environ.get("MAX_WORKERS_PER_MODEL",   "4"))

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


def get_active_count(dispatch: ModelDispatch) -> int:
    """get the number of tasks running for this model"""
    count = 0
    for status in ("RUNNING", "PENDING"):
        resp = ecs.list_tasks(
            cluster=CLUSTER_ARN,
            desiredStatus=status,
            family=dispatch.family,
            maxResults=100,
        )
        count += len(resp.get("taskArns", []))
    return count


def get_queue_depth(dispatch: ModelDispatch) -> int:
    """get the number of requests waiting for this model"""
    attrs = sqs.get_queue_attributes(
        QueueUrl=dispatch.queue_url,
        AttributeNames=["ApproximateNumberOfMessages"],
    )["Attributes"]
    return int(attrs.get("ApproximateNumberOfMessages", 0))


def is_active(dispatch: ModelDispatch) -> bool:
    return get_active_count(dispatch) > 0


def get_capacity_provider(dispatch: ModelDispatch) -> str:
    return {
        "lrg": os.environ.get("ECS_CAPACITY_PROVIDER_GPU_LRG"),
        "sm": os.environ.get("ECS_CAPACITY_PROVIDER_GPU_SM"),
    }.get(dispatch.gpu_tier, os.environ.get("ECS_CAPACITY_PROVIDER_BIG_CPU"))


def launch(dispatch: ModelDispatch) -> None:
    ecs.run_task(
        cluster=CLUSTER_ARN,
        taskDefinition=dispatch.task_definition,
        clientToken=uuid.uuid4().hex,
        count=1,
        networkConfiguration={
            "awsvpcConfiguration": {
                "subnets": SUBNETS,
                "securityGroups": SECURITY_GROUPS,
            }
        },
        capacityProviderStrategy=[
            {
                "capacityProvider": get_capacity_provider(dispatch),
                "weight": 1,
                "base": 0,
            }
        ],
    )


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


def handle_request_queued(evt: LifecycleEvent) -> None:
    logger.info("REQUEST_QUEUED for '%s'", evt.model_name)

    try:
        models = load_model_config()
        dispatch = models.get(evt.model_hash)
    except Exception as e:
        logger.error("failed to load model config: %s", e)
        return

    if not dispatch:
        logger.error("unknown model hash: %s", evt.model_hash)
        return

    max_instances_per_model = 4
    active = get_active_count(dispatch)
    depth = get_queue_depth(dispatch)
    estimated = min(max_instances_per_model, max(1, depth // dispatch.msg_per_instance))

    logger.info("model='%s' queue_depth=%d active=%d, estimate=%d", evt.model_name, depth, active, estimated)

    if active >= estimated:
        logger.info(
            "model='%s' active=%d >= estimated=%d -- skipping",
            evt.model_name, active, estimated,
        )
        return

    launch(dispatch)

    publish(
        LifecycleEvent(
            event_type=EventType.WORKER_LAUNCHING,
            model_name=evt.model_name,
            model_hash=evt.model_hash,
            message_id=evt.message_id,
        )
    )


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

EVENT_HANDLERS = {
    EventType.REQUEST_QUEUED: handle_request_queued,
}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def handler(event, context):
    for record in event.get("Records", []):
        try:
            evt = LifecycleEvent.from_sns_record(record)
        except Exception as e:
            logger.error("failed to parse SNS record: %s", e)
            continue

        handle = EVENT_HANDLERS.get(evt.event_type)
        if not handle:
            logger.debug("no handler for event type '%s' -- skipping", evt.event_type)
            continue

        try:
            handle(evt)
        except Exception as e:
            logger.exception("handler for '%s' raised: %s", evt.event_type, e)
