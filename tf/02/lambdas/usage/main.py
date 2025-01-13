"""account usage logging

Handles receipt of usage metrics on SQS and writing to DynamoDB
"""
import os
import logging
import json

from datetime import datetime
from dynawrap import DynamodbWrapper, DBItem


logger = logging.getLogger()
logger.setLevel(os.getenv("LOG_LEVEL", logging.WARNING))
USAGE_TABLE_NAME = os.environ["DYNAMODB_USAGE_TABLE"]


class RawUsageMetrics(DBItem):
    """Raw metrics table row definition."""

    table_name = USAGE_TABLE_NAME
    pk_pattern = "METRIC#RAW#USER#{user_id}"
    sk_pattern = "DATE#{date}#OP#{operation}"


dynamodb_wrapper = DynamodbWrapper(RawUsageMetrics)


def sqs_handler(event, context):
    """
    Lambda function handler for processing SQS messages.

    Args:
        event: AWS Lambda event object containing SQS records.
        context: AWS Lambda context object.

    Writes metrics data to DynamoDB.
    """
    for idx, message in enumerate(event["Records"]):
        # send the data to dynamodb
        logger.debug("message: '%s'", message)

        try:
            # Parse message payload
            body = json.loads(message["body"])
        except Exception as e:
            logger.exception("failed to parse payload [%s]", str(e))
            continue

        logger.debug("[%i/%i] processing message: %s", idx, len(event["Records"]), body)

        # Extract or compute necessary fields
        operation = body.get("operation", "unknown")
        userid = body.get("user_id", "unknown")
        now = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

        # Construct data for DynamoDB
        item_data = {
            "operation": operation,
            "user_id": userid,
            "date": now,
            "data": json.dumps(body),
        }

        # Save data to DynamoDB
        try:
            usage_item = RawUsageMetrics(dynamodb_wrapper)
            usage_item.save(item_data)

            logger.debug("wrote to ddb: %s", item_data)
        except Exception as e:
            logger.error("Failed to process message: %s, error: %s", message, str(e))
