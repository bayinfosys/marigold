"""Launcher -- SQS-triggered Lambda.

Drains the launch FIFO queue. For each launch request, checks current
active task count and calls run_task if workers are still needed.

On ECS provisioning limit: raises so SQS returns the message to the queue
after the visibility timeout. The rate of run_task calls naturally
self-limits to the rate at which the cluster can accept new tasks.

NB: this **might** block task launch if there is an running worker.
"""

import json
import logging
import os
import uuid

import boto3
from botocore.exceptions import ClientError
from shared.models import ModelDispatch

logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))

s3 = boto3.client("s3")
ecs = boto3.client("ecs")
sqs = boto3.client("sqs")

CLUSTER_ARN = os.environ["ECS_CLUSTER_ARN"]
SUBNETS = os.environ["ECS_SUBNETS"].split(",")
SECURITY_GROUPS = os.environ["ECS_SECURITY_GROUPS"].split(",")
DEFAULT_MAX_WORKERS = int(os.environ.get("DEFAULT_MAX_WORKERS", "4"))

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
    """get the list of tasks where the status is or will be RUNNING
    NB: we must avoid STOPPED or this will ruin the estimation
    """
    resp = ecs.list_tasks(
        cluster=CLUSTER_ARN,
        desiredStatus="RUNNING",
        family=dispatch.family,
        maxResults=100,
    )
    return len(resp.get("taskArns", []))


def get_capacity_provider(dispatch: ModelDispatch) -> str:
    return {
        "lrg": os.environ.get("ECS_CAPACITY_PROVIDER_GPU_LRG"),
        "sm": os.environ.get("ECS_CAPACITY_PROVIDER_GPU_SM"),
    }.get(dispatch.gpu_tier, os.environ.get("ECS_CAPACITY_PROVIDER_BIG_CPU"))


def run_task(dispatch: ModelDispatch) -> None:
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


def handler(event, context):
    for record in event.get("Records", []):
        try:
            body = json.loads(record["body"])
            model_name = body["model_name"]
            model_hash = body["model_hash"]
        except Exception as e:
            logger.error("failed to parse launch record: %s", e)
            continue

        try:
            models = load_model_config()
            dispatch = models.get(model_hash)
        except Exception as e:
            logger.error("failed to load model config: %s", e)
            continue

        if not dispatch:
            logger.error(
                "unknown model hash: %s -- dropping launch request", model_hash
            )
            continue

        max_workers = (
            dispatch.max_workers
            if dispatch.max_workers is not None
            else DEFAULT_MAX_WORKERS
        )
        active = get_active_count(dispatch)

        logger.info(
            "model='%s' active=%d max=%d family=%s",
            model_name,
            active,
            max_workers,
            dispatch.family,
        )

        if active >= max_workers:
            logger.warning(
                "model='%s' active=%d >= max=%d -- skipping",
                model_name,
                active,
                max_workers,
            )
            continue

        try:
            run_task(dispatch)
            logger.info("model='%s' task launched active_before=%d", model_name, active)
        except ClientError as e:
            if "provisioning capacity limit" in str(e).lower():
                logger.warning(
                    "model='%s' provisioning limit hit -- returning to queue",
                    model_name,
                )
                raise  # SQS visibility timeout returns message to queue

            logger.exception("model='%s' provisioning failure '%s'", model_name, str(e))
            raise
