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

FIXME (aws-removal): _dynawrap below is a stub -- needs an injected
dynawrap DBBackend, same as model_dummy.py / persistence.py.

FIXME (aws-removal): _load_queue_map() read models_config.json from S3.
Locally this wants to come from models.yaml via models.catalogue
(already loaded at API/worker startup elsewhere) rather than a fresh
fetch here -- see the identical stub in api_handler.py, which has the
same function duplicated.
"""

import hashlib
import json
import logging
import os
from datetime import datetime, timezone

import runfox as rfx
from runfox.results import Complete, Dispatch, Halt

from .models import WorkflowExecution, parse_workflow_execution_id
from .runner import make_message_body_fn, make_queue_url_fn

logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))

# TODO: inject a dynawrap DBBackend rather than constructing one here.
_dynawrap = None

STATE_TABLE = os.getenv("WORKFLOW_STATE_TABLE")


def _load_queue_map() -> dict:
    # TODO: build this from models.catalogue / models.yaml instead of
    # an S3-hosted models_config.json. See the duplicate of this
    # function in api_handler.py -- fix both or collapse to one.
    dummy_name = "dummy"
    dummy_md5 = hashlib.md5(dummy_name.encode()).hexdigest()
    return {dummy_md5: os.environ.get("QUEUE_URL_DUMMY", "")}


QUEUE_MAP = _load_queue_map()


def _make_backend(user_id: str) -> rfx.Backend:
    """Construct a runfox Backend for workflow state management.

    This is distinct from the dynawrap DBBackend used for
    WorkflowExecution and WorkflowStep model operations.

    FIXME (aws-removal): the real branch below (SQSRunner/DynamoDBStore)
    is AWS-only and unreachable until runfox has non-AWS Store/Runner
    implementations to construct instead -- that's the shared-backend
    work, not something to fake here.
    """
    if STATE_TABLE is not None:
        # FIXME: DynamoDBStore/SQSRunner removed -- runfox needs a
        # Postgres-backed Store and a QueueBackend-backed Runner
        # before this branch can do anything.
        logger.warning("no local runfox backend implemented yet")
        return None
    else:
        # TODO: add in process workflow
        logger.warning("no backend configured (STATE_TABLE unset)")
        return None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_execution(user_id: str, workflow_execution_id: str) -> WorkflowExecution:
    workflow_id, execution_id = parse_workflow_execution_id(workflow_execution_id)
    # FIXME: _dynawrap is None until injected -- raises AttributeError.
    item = _dynawrap.get(
        STATE_TABLE,
        WorkflowExecution,
        user_id=user_id,
        workflow_id=workflow_id,
        execution_id=execution_id,
    )
    if item is None:
        raise KeyError(f"execution not found: {workflow_execution_id}")
    return item


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
    # FIXME: _dynawrap is None until injected.
    _dynawrap.save(STATE_TABLE, updated)
    logger.info("workflow_execution_id=%s status=%s", workflow_execution_id, status)


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


def handler(event, context):
    """
    TODO (aws-removal): this is invoked directly by name from
    dynamodb_stream_handler.py's lambda_client.invoke() call today.
    Once the trigger mechanism is rebuilt (see that file's TODO), this
    probably becomes a plain function call rather than a "handler"
    with an (event, context) signature at all.
    """
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
