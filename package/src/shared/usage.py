"""Usage tracking and metrics.

record_usage() is the single call site for all handler modules. It
builds a ModelUsageStats, writes to the configured metrics backend,
and returns the stats for inclusion in the handler response.

Both metrics backends (DynamoDB and SQS) use UsageItem as the canonical
data shape. The SQS path serialises the full UsageItem dict so that a
downstream consumer can reconstruct and persist it without data loss.
"""

import logging
import os
import json

import boto3
from botocore.exceptions import NoRegionError
from dynawrap.backends.dynamodb import DynamoDBBackend

from shared.enums import ModelType
from shared.usage_models import ModelUsageStats, UsageItem

logger = logging.getLogger(__name__)

try:
    _ddb = boto3.client("dynamodb")
    _dynawrap = DynamoDBBackend(_ddb)
except NoRegionError:
    logger.warning("aws unavailable")
    _ddb = None
    _dynawrap = None


def get_memory_usage() -> int:
    import resource
    return 1 + int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0)


def record_usage(
    user_id: str,
    model_type: ModelType,
    modelname: str,
    duration: float,
    inference: float,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> ModelUsageStats:
    """Build a ModelUsageStats instance, submit to the metrics backend,
    and return the stats for inclusion in the handler response.
    """
    stats = ModelUsageStats(
        duration=int(duration*1000),
        inference=int(inference*1000),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        memory_usage=get_memory_usage(),
    )
    item = UsageItem.from_model_stats(
        stats=stats,
        user_id=user_id,
        model_type=model_type.value,
        model_name=modelname,
    )
    update_metrics(item)
    return stats


def _update_metrics_dynamodb(item: UsageItem):
    table = os.environ["DYNAMODB_USAGE_TABLE"]
    try:
        _dynawrap.save(table, item)
    except Exception as e:
        logger.exception(
            "[%s/%s] failed to write metrics to '%s' [%s]",
            item.user_id, item.operation, table, str(e),
        )


def _update_metrics_sqs(item: UsageItem):
    sqs_client = boto3.client("sqs")
    queue_url = os.getenv("METRICS_QUEUE_URL")

    if not queue_url:
        logger.warning("METRICS_QUEUE_URL not set, metrics not logged")
        return

    try:
        response = sqs_client.send_message(
            QueueUrl=queue_url,
            MessageBody=item.model_dump_json(),
        )
        logger.info(
            "metrics sent to '%s' [%s]", queue_url, response["MessageId"]
        )
    except Exception as e:
        logger.error(
            "failed to send metrics to '%s' [%s]", queue_url, str(e)
        )


def update_metrics(item: UsageItem):
    if "DYNAMODB_USAGE_TABLE" in os.environ:
        _update_metrics_dynamodb(item)
    elif "METRICS_QUEUE_URL" in os.environ:
        _update_metrics_sqs(item)
    else:
        logger.warning(
            "[%s/%s] no metrics backend configured",
            item.user_id,
            item.operation,
        )
