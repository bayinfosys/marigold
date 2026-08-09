"""
workflow/dynamodb_stream_handler.py -- DynamoDB Streams router Lambda.

Subscribed to DynamoDB Streams on the workflow steps results table.
Identifies WORKFLOW# message_id records, parses the composite key,
and invokes the executor Lambda asynchronously for each step result.

No runfox dependency. No DynamoDB writes.

Environment variables
---------------------
WORKFLOW_EXECUTOR_FUNCTION  name or ARN of the executor Lambda

FIXME (aws-removal): this whole file's premise -- a stream subscription
firing on a table write -- has no direct local equivalent. Options for
the backend-agnostic rebuild: (a) PostgresNotificationBackend once it
exists, publishing a "step complete" event that a listener consumes and
calls executor.handler() directly, in-process, rather than invoking it
as a separate function; or (b) skip the trigger entirely and have
whatever writes the WorkflowStep completion record (model_dummy.py,
worker.py-equivalent) call the executor directly itself. (b) is
probably simpler unless there's a reason to decouple "step wrote" from
"workflow advanced" the way DynamoDB Streams did.

_extract_result_payload and _extract_user_id below are already dead
code independent of the AWS question -- handler() uses
_dynawrap.from_stream_record() instead of either of them. Not touched
here; flagging since it's easy to miss.
"""

import json
import logging
import os

from .models import WorkflowStep

logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))

# TODO: inject a dynawrap DBBackend rather than constructing one here.
_dynawrap = None

WORKFLOW_EXECUTOR_FUNCTION = os.environ.get("WORKFLOW_EXECUTOR_FUNCTION", "")


def _extract_result_payload(new_image: dict) -> dict:
    """
    Extract the step output dict from a DynamoDB Streams new image.

    The output field is stored as a JSON string in the DynamoDB item.
    Returns an empty dict if the field is absent or unparseable.

    NOTE: unused by handler() below -- see module docstring.
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

    NOTE: unused by handler() below -- see module docstring.
    """
    pk = new_image.get("pk", {}).get("S", "")
    if not pk.startswith("USER#"):
        raise ValueError(f"unexpected PK format: {pk!r}")
    parts = pk.split("#")
    if len(parts) < 4:
        raise ValueError(f"PK has too few components: {pk!r}")
    return parts[1]


def handler(event, context):
    """
    TODO (aws-removal): event["Records"] is DynamoDB Streams' shape.
    See module docstring for the two rebuild options.
    """
    logger.info("stream handler received %d records", len(event["Records"]))
    for record in event["Records"]:
        if record["eventName"] not in ("INSERT", "MODIFY"):
            continue

        try:
            # FIXME: _dynawrap is None until injected.
            step = _dynawrap.from_stream_record(record, WorkflowStep)
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

        # FIXME: lambda_client removed -- see module docstring for the
        # replacement (call executor.handler() directly, or route
        # through the notification backend once it exists).
        logger.warning(
            "executor invocation not implemented locally: %s", payload
        )
