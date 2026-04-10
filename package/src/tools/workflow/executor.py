"""
workflow/executor.py -- Workflow executor Lambda.

Invoked asynchronously by the stream handler Lambda when a workflow step
result arrives. Advances the runfox workflow state machine:

    load state -> on_step_result() -> advance() -> dispatch next steps

Handles Dispatch, Complete, and Halt outcomes from advance().
Writes terminal state (complete, halted) back to WORKFLOW_STATE_TABLE.

Environment variables
---------------------
WORKFLOW_STATE_TABLE      DynamoDB table for WorkflowExecution records
WORKFLOW_TASKS_TABLE      DynamoDB table for runfox SQSRunner tasks
AWS_S3_ASSETS_BUCKET_NAME S3 bucket containing models_config.json
MODELS_CONFIG_S3_OBJECT   S3 key for models_config.json
QUEUE_URL_DUMMY           SQS queue URL for the dummy model
"""

import hashlib
import json
import logging
import os
from datetime import datetime, timezone

import boto3
import runfox as rfx
from runfox.backend.aws import DynamoDBStore, SQSRunner
from runfox.results import Complete, Dispatch, Halt

from .models import WorkflowExecution, parse_workflow_execution_id
from .runner import make_message_body_fn, make_queue_url_fn

logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))

ddb = boto3.client("dynamodb")
s3 = boto3.client("s3")

STATE_TABLE = os.environ["WORKFLOW_STATE_TABLE"]


def _load_queue_map() -> dict:
    bucket = os.environ["AWS_S3_ASSETS_BUCKET_NAME"]
    key = os.environ["MODELS_CONFIG_S3_OBJECT"]
    obj = s3.get_object(Bucket=bucket, Key=key)
    config = json.loads(obj["Body"].read())
    queue_map = {k: v["queue_url"] for k, v in config.items()}

    dummy_name = "dummy"
    dummy_md5 = hashlib.md5(dummy_name.encode()).hexdigest()
    queue_map[dummy_md5] = os.environ["QUEUE_URL_DUMMY"]
    return queue_map


QUEUE_MAP = _load_queue_map()


def _make_backend(user_id: str) -> rfx.Backend:
    return rfx.Backend(
        store=DynamoDBStore(table=STATE_TABLE),
        runner=SQSRunner(
            tasks_table=os.environ["WORKFLOW_TASKS_TABLE"],
            queue_url=make_queue_url_fn(QUEUE_MAP),
            message_body_fn=make_message_body_fn(user_id),
        ),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_execution(user_id: str, workflow_execution_id: str) -> WorkflowExecution:
    workflow_id, execution_id = parse_workflow_execution_id(workflow_execution_id)
    return WorkflowExecution.read(
        ddb,
        STATE_TABLE,
        user_id=user_id,
        workflow_id=workflow_id,
        execution_id=execution_id,
    )


def _write_completion(
    user_id: str,
    workflow_execution_id: str,
    status: str,
    outcome: dict,
) -> None:
    existing = _load_execution(user_id, workflow_execution_id)
    updated = existing.model_copy(
        update={
            "status": status,
            "outcome": json.dumps(outcome),
            "updated_at": _now(),
        }
    )
    ddb.put_item(TableName=STATE_TABLE, Item=updated.to_dynamo_item())
    logger.info("workflow_execution_id=%s status=%s", workflow_execution_id, status)


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


def handler(event, context):
    workflow_execution_id = event["workflow_execution_id"]
    user_id = event["user_id"]
    op = event["op"]
    run_id = int(event["run_id"])
    output = event["output"]

    logger.info(
        "workflow_execution_id=%s op=%s run_id=%d",
        workflow_execution_id,
        op,
        run_id,
    )

    execution = _load_execution(user_id, workflow_execution_id)

    if execution.status == "cancelled":
        logger.info(
            "workflow_execution_id=%s is cancelled, skipping",
            workflow_execution_id,
        )
        return

    backend = _make_backend(user_id)
    record = backend.load(workflow_execution_id)
    current_run_id = record.steps[op].run_id
    if current_run_id != run_id:
        logger.warning(
            "stale result: op=%s expected run_id=%d got run_id=%d, skipping",
            op,
            current_run_id,
            run_id,
        )
        return

    wf = rfx.Workflow.resume(workflow_execution_id, backend)
    step_result = wf.on_step_result(op, output)

    if isinstance(step_result, Halt):
        _write_completion(
            user_id=user_id,
            workflow_execution_id=workflow_execution_id,
            status="halted",
            outcome=step_result.result,
        )
        return

    result = wf.advance()

    if isinstance(result, Dispatch):
        backend.dispatch(wf.id, result.jobs)
        logger.info(
            "workflow_execution_id=%s dispatched %d jobs",
            workflow_execution_id,
            len(result.jobs),
        )

    elif isinstance(result, Complete):
        _write_completion(
            user_id=user_id,
            workflow_execution_id=workflow_execution_id,
            status="complete",
            outcome=result.outcome,
        )
