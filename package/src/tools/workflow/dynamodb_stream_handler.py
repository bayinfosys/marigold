"""
workflow/router.py -- DynamoDB Streams router Lambda.

Subscribed to DynamoDB Streams on the workflow steps results table.
Identifies WORKFLOW# message_id records, parses the composite key,
and invokes the executor Lambda asynchronously for each step result.

No runfox dependency. No DynamoDB writes.

Environment variables
---------------------
WORKFLOW_EXECUTOR_FUNCTION  name or ARN of the executor Lambda
"""

import json
import logging
import os

import boto3

from .models import WorkflowStep

logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))

lambda_client = boto3.client("lambda")

WORKFLOW_EXECUTOR_FUNCTION = os.environ["WORKFLOW_EXECUTOR_FUNCTION"]


def _extract_result_payload(new_image: dict) -> dict:
    """
    Extract the step output dict from a DynamoDB Streams new image.

    The output field is stored as a JSON string in the DynamoDB item.
    Returns an empty dict if the field is absent or unparseable.
    """
    output_str = new_image.get("output", {}).get("S", "{}")
    try:
        return json.loads(output_str)
    except (json.JSONDecodeError, TypeError):
        logger.warning("failed to parse output field, returning empty dict")
        return {}


def _extract_user_id(new_image: dict) -> str:
    """
    Extract user_id from the DynamoDB Streams new image PK attribute.

    PK format: USER#{user_id}#WORKFLOW#{workflow_id}
    Strips the USER# prefix and takes the first component.
    """
    pk = new_image.get("pk", {}).get("S", "")
    if not pk.startswith("USER#"):
        raise ValueError(f"unexpected PK format: {pk!r}")
    # PK is USER#{user_id}#WORKFLOW#{workflow_id}
    # split on # and take index 1
    parts = pk.split("#")
    if len(parts) < 4:
        raise ValueError(f"PK has too few components: {pk!r}")
    return parts[1]


def handler(event, context):
    logger.info("stream handler received %d records", len(event["Records"]))
    for record in event["Records"]:
        if record["eventName"] not in ("INSERT", "MODIFY"):
            continue

        try:
            step = WorkflowStep.from_stream_record(record)
        except ValueError as e:
            logger.info("skipping record: %s", e)
            continue

        if step.status != "complete":
            continue

        workflow_execution_id = f"{step.workflow_id}#{step.execution_id}"
        output = json.loads(step.output) if step.output else {}

        payload = {
            "workflow_execution_id": workflow_execution_id,
            "user_id": step.user_id,
            "op": step.op,
            "run_id": step.run_id,
            "output": output,
        }

        logger.info(
            "invoking executor for workflow_execution_id=%s op=%s run_id=%d",
            workflow_execution_id,
            step.op,
            step.run_id,
        )

        lambda_client.invoke(
            FunctionName=WORKFLOW_EXECUTOR_FUNCTION,
            InvocationType="Event",
            Payload=json.dumps(payload),
        )
