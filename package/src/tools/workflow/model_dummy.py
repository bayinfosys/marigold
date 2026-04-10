"""
workflow/model_dummy.py -- Dummy model Lambda.

Triggered by SQS messages on the dummy model queue. Handles three
method values in model_inputs:

    echo    returns all model_inputs fields unchanged
    true    returns {"result": True}
    false   returns {"result": False}

Writes the result back to WORKFLOW_STEPS_TABLE by updating the
dispatched WorkflowStep record to complete. The stream handler
Lambda then picks up the state change via DynamoDB Streams and
invokes the executor.

Environment variables
---------------------
WORKFLOW_STEPS_TABLE    DynamoDB table name for step records
"""

import json
import logging
import os
from datetime import datetime, timezone

import boto3
from shared.sqs_models import MarigoldSQSMessage

from .models import WorkflowStep, step_id

logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))

ddb = boto3.client("dynamodb")

STEPS_TABLE = os.environ["WORKFLOW_STEPS_TABLE"]


def _compute_output(method: str, model_inputs: dict) -> dict:
    if method == "echo":
        return model_inputs
    elif method == "true":
        return {"result": True}
    elif method == "false":
        return {"result": False}

    raise ValueError(f"unknown dummy method: {method!r}")


def _handle_message(body: dict) -> None:
    msg = MarigoldSQSMessage.model_validate(body)

    method = msg.model_inputs.get("method", "echo")
    payload = {k: v for k, v in msg.model_inputs.items() if k != "method"}

    try:
        model_output = {"model_output": _compute_output(method, payload)}
    except Exception as e:
        logger.error("failed to process '%s' with '%s'", json.dumps(body), str(e))
        logger.exception(json.dumps(body))
        model_output = {"error": "model execution failed"}

    workflow_id, execution_id = msg.workflow_execution_id.split("#", 1)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    completed_step = WorkflowStep(
        user_id=msg.user_id,
        workflow_id=workflow_id,
        execution_id=execution_id,
        op=msg.op,
        step_id=step_id(msg.op),
        run_id=msg.run_id,
        model_type=msg.model_type,
        model_name=msg.model_name,
        status="complete",
        submitted_at=now,
        completed_at=now,
        output=json.dumps(model_output),
    )
    ddb.put_item(TableName=STEPS_TABLE, Item=completed_step.to_dynamo_item())

    logger.info(
        "dummy method=%s workflow_execution_id=%s op=%s run_id=%d complete",
        method,
        workflow_id,
        msg.op,
        msg.run_id,
    )


def handler(event, context):
    for record in event["Records"]:
        try:
            body = json.loads(record["body"])
            _handle_message(body)
        except Exception:
            logger.exception(
                "failed to process record: %s", record.get("messageId", "unknown")
            )
            raise
