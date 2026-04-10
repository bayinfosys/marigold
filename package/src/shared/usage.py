"""Usage tracking and metrics.

ModelUsageStats is defined in usage_models rather than in api/models.py so that
handler modules and shared infrastructure can import it without depending
on the API layer.
"""

import json
import logging
import os
from datetime import datetime

from botocore.exceptions import NoRegionError
import boto3
from shared.enums import ModelType

from .usage_models import ModelUsageStats

logger = logging.getLogger(__name__)

try:
    _dynamodb = boto3.client("dynamodb", endpoint_url=os.getenv("DYNAMODB_ENDPOINT"))
except NoRegionError:
    logger.warning("aws unavailable")
    _dynamodb = None


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------


def get_memory_usage() -> int:
    """Return peak process memory usage in KB."""
    import resource

    return 1 + int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0)


# ---------------------------------------------------------------------------
# record_usage
# ---------------------------------------------------------------------------


def record_usage(
    user_id: str,
    model_type: ModelType,
    modelname: str,
    duration: float,
    inference: float,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> ModelUsageStats:
    """Build a ModelUsageStats instance and submit it to the metrics backend.

    Returns the stats object so callers can include it in their response.
    """
    usage = ModelUsageStats(
        duration=duration,
        inference=inference,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        memory_usage=get_memory_usage(),
    )
    update_metrics(user_id, model_type, modelname, usage.model_dump())
    return usage


# ---------------------------------------------------------------------------
# Metrics backends
# ---------------------------------------------------------------------------


def _metric_body(
    user_id: str, model_type: ModelType, model_name: str, metrics: dict
) -> dict:
    return dict(
        user_id=user_id,
        operation="%s/%s" % (model_type.value, model_name),
        **metrics,
    )


def _update_metrics_sqs(
    user_id: str, model_type: ModelType, model_name: str, metrics: dict
):
    sqs_client = boto3.client("sqs", endpoint_url=os.getenv("AWS_SQS_ENDPOINT_URL"))
    queue_url = os.getenv("METRICS_QUEUE_URL")

    if not queue_url:
        logger.warning("METRICS_QUEUE_URL not set, metrics not logged")
        return

    body = _metric_body(user_id, model_type, model_name, metrics)
    try:
        response = sqs_client.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps(body),
        )
        logger.info("metrics sent to '%s' [%s]", queue_url, response["MessageId"])
    except Exception as e:
        logger.error("failed to send metrics to '%s' [%s]", queue_url, str(e))


def _update_metrics_dynamodb(
    user_id: str, model_type: ModelType, model_name: str, metrics: dict
):
    table = os.environ["DYNAMODB_USAGE_TABLE"]
    body = _metric_body(user_id, model_type, model_name, metrics)
    now = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    operation = body["operation"]

    try:
        _dynamodb.put_item(
            TableName=table,
            Item={
                "PK": {"S": "METRIC#RAW#USER#%s" % user_id},
                "SK": {"S": "DATE#%s#OP#%s" % (now, operation)},
                "operation": {"S": operation},
                "user_id": {"S": user_id},
                "date": {"S": now},
                "data": {"S": json.dumps(body)},
            },
        )
    except Exception as e:
        logger.exception(
            "[%s/%s.%s] failed to write metrics to '%s' [%s]",
            user_id,
            model_type,
            model_name,
            table,
            str(e),
        )


def update_metrics(user_id: str, model_type: ModelType, model_name: str, metrics: dict):
    """Dispatch metrics to whichever backend is configured.

    Checks DYNAMODB_USAGE_TABLE first, then METRICS_QUEUE_URL. If neither
    is set, logs a warning and continues.
    """
    if "DYNAMODB_USAGE_TABLE" in os.environ:
        _update_metrics_dynamodb(user_id, model_type, model_name, metrics)
    elif "METRICS_QUEUE_URL" in os.environ:
        _update_metrics_sqs(user_id, model_type, model_name, metrics)
    else:
        logger.warning(
            "[%s/%s.%s] no metrics backend configured",
            user_id,
            model_type.value,
            model_name,
        )
