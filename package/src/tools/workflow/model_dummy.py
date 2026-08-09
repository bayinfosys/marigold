"""
workflow/model_dummy.py -- Dummy model Lambda.

Triggered by messages on the dummy model queue. Handles three
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

FIXME (aws-removal): the write path below (_dynawrap.save) assumed a
DynamoDBBackend built directly from a boto3 client. That construction
has been stripped -- _dynawrap is a stub until the workflow package
has a backend-agnostic persistence layer to inject instead.
"""

import json
import logging
import os
from datetime import datetime, timezone

from shared.schedule_models import MarigoldMessage

from .models import WorkflowStep, step_id

logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))

# TODO: replace with an injected dynawrap DBBackend (Postgres or
# whatever main.py wires up), passed into this module rather than
# constructed here -- mirrors receiver_logic.py/results_cache.py,
# which already take an injected backend instead of building one
# from a boto3 client at import time.
_dynawrap = None

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
    msg = MarigoldMessage.model_validate(body)

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

    # FIXME: _dynawrap is None until the backend is injected -- this
    # raises AttributeError if actually called, which is expected for
    # now (see module docstring).
    _dynawrap.save(STEPS_TABLE, completed_step)

    logger.info(
        "dummy method=%s workflow_execution_id=%s op=%s run_id=%d complete",
        method,
        workflow_id,
        msg.op,
        msg.run_id,
    )


def handler(event, context):
    """
    TODO (aws-removal): this signature and body assume an SQS-triggered
    Lambda invocation (event["Records"], each with a "body" string).
    A local equivalent needs the same shape QueueWorker already uses in
    worker.py -- a loop over queue_backend.receive() rather than a
    Records list handed in by the runtime.
    """
    for record in event["Records"]:
        try:
            body = json.loads(record["body"])
            _handle_message(body)
        except Exception:
            logger.exception(
                "failed to process record: %s", record.get("messageId", "unknown")
            )
            raise
