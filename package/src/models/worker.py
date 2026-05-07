"""SQS worker loop for model inference tasks.

Reads one message at a time from the configured SQS queue, validates
the payload, runs inference, writes results to the appropriate backing
stores, and deletes the message.

Execution contexts
------------------
Direct API jobs (sqs_msg.workflow_execution_id is None):
    Status written to results cache under API#{message_id}.
    Client polls GET /{mode}/{task}/{message_id} for the result.

Workflow step jobs (sqs_msg.workflow_execution_id is set):
    Status written to results cache under
    WORKFLOW#{workflow_execution_id}#STEP#{op}#RUN#{run_id}.
    Step completion also written to WORKFLOW_STEPS_TABLE to trigger
    the executor Lambda via DynamoDB Streams.

Both contexts always write to the results cache, giving a unified
view of all job activity across the platform.

Idle behaviour
--------------
When the queue is empty the worker continues polling until idle_timeout
seconds have elapsed since the last message was processed, then exits.
Set idle_timeout=0 to exit on the first empty poll response.
"""

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone

import boto3
from dynawrap.backends.dynamodb import DynamoDBBackend
from pydantic import ValidationError
from shared.db_models import ResultsItem, WorkflowStep
from shared.registry import _SPECS, BaseModelHandler
from shared.sqs_models import MarigoldSQSMessage, make_job_id
from models.standard_loader import ModelNotFoundError

logger = logging.getLogger(__name__)

_LONG_POLL_WAIT = 20  # seconds; SQS maximum
_HEARTBEAT_BUFFER = 5  # seconds before timeout to extend visibility

DYNAMODB_TABLE = os.environ.get("DYNAMODB_RESULTS_TABLE", "")

_ddb = boto3.client("dynamodb")
_dynawrap = DynamoDBBackend(_ddb)


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------


def _heartbeat(
    client,
    queue_url: str,
    receipt_handle: str,
    visibility_timeout: int,
    stop: threading.Event,
):
    """Extend SQS visibility timeout periodically until stop is set.

    Fires every (visibility_timeout - buffer) seconds to keep the message
    invisible while inference is running.
    """
    interval = max(1, visibility_timeout - _HEARTBEAT_BUFFER)
    while not stop.wait(timeout=interval):
        try:
            client.change_message_visibility(
                QueueUrl=queue_url,
                ReceiptHandle=receipt_handle,
                VisibilityTimeout=visibility_timeout,
            )
            logger.debug("visibility timeout extended")
        except Exception as e:
            logger.warning("failed to extend visibility timeout: %s", e)


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------


def _results_item(
    sqs_msg: MarigoldSQSMessage, status: str, response: dict = None
) -> ResultsItem:
    return ResultsItem(
        user_id=sqs_msg.user_id,
        job_id=make_job_id(sqs_msg),
        status=status,
        response=json.dumps(response) if response else None,
        ttl=ResultsItem.make_ttl(),
    )


def _write_results(sqs_msg: MarigoldSQSMessage, status: str, response: dict = None):
    """Write a status update to the results cache."""
    if not DYNAMODB_TABLE:
        logger.warning(
            "[%s/%s] DYNAMODB_RESULTS_TABLE not set, skipping results write",
            sqs_msg.user_id,
            sqs_msg.message_id,
        )
        return
    item = _results_item(sqs_msg, status, response)
    try:
        _dynawrap.save(DYNAMODB_TABLE, item)
    except Exception as e:
        logger.exception(
            "[%s/%s] failed to write results [%s]",
            sqs_msg.user_id,
            sqs_msg.message_id,
            str(e),
        )


def _write_workflow_step_complete(
    sqs_msg: MarigoldSQSMessage,
    output: dict,
):
    steps_table = os.getenv("WORKFLOW_STEPS_TABLE")
    if not steps_table:
        logger.warning(
            "[%s/%s] WORKFLOW_STEPS_TABLE not set, skipping step write",
            sqs_msg.user_id,
            sqs_msg.message_id,
        )
        return

    workflow_id, execution_id = sqs_msg.workflow_execution_id.split("#", 1)
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    step = WorkflowStep(
        user_id=sqs_msg.user_id,
        workflow_id=workflow_id,
        execution_id=execution_id,
        op=sqs_msg.op,
        step_id=WorkflowStep.make_step_id(sqs_msg.op),
        run_id=sqs_msg.run_id,
        model_type=sqs_msg.model_type,
        model_name=sqs_msg.model_name,
        status="complete",
        submitted_at=now,
        completed_at=now,
        output=json.dumps(output),
    )

    try:
        _dynawrap.save(steps_table, step)
        logger.info(
            "[%s/%s] workflow step complete written",
            sqs_msg.user_id,
            sqs_msg.message_id,
        )
    except Exception as e:
        logger.exception(
            "[%s/%s] failed to write workflow step complete [%s]",
            sqs_msg.user_id,
            sqs_msg.message_id,
            str(e),
        )


def _write_workflow_step_failed(
    sqs_msg: MarigoldSQSMessage,
    error: str,
):
    steps_table = os.getenv("WORKFLOW_STEPS_TABLE")
    if not steps_table:
        logger.warning(
            "[%s/%s] WORKFLOW_STEPS_TABLE not set, skipping step failure write",
            sqs_msg.user_id,
            sqs_msg.message_id,
        )
        return

    workflow_id, execution_id = sqs_msg.workflow_execution_id.split("#", 1)
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    step = WorkflowStep(
        user_id=sqs_msg.user_id,
        workflow_id=workflow_id,
        execution_id=execution_id,
        op=sqs_msg.op,
        step_id=WorkflowStep.make_step_id(sqs_msg.op),
        run_id=sqs_msg.run_id,
        model_type=sqs_msg.model_type,
        model_name=sqs_msg.model_name,
        status="failed",
        submitted_at=now,
        completed_at=now,
        output=json.dumps({"error": error}),
    )

    try:
        _dynawrap.save(steps_table, step)
    except Exception as e:
        logger.exception(
            "[%s/%s] failed to write workflow step failure [%s]",
            sqs_msg.user_id,
            sqs_msg.message_id,
            str(e),
        )


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------


class SQSWorker:
    """SQS long-poll loop for any BaseModelHandler."""

    def __init__(
        self,
        queue_url: str,
        model: BaseModelHandler,
        visibility_timeout: int,
        idle_timeout: int,
    ):
        self.queue_url = queue_url
        self.model = model
        self.visibility_timeout = visibility_timeout
        self.idle_timeout = idle_timeout
        self.client = boto3.client("sqs")
        self._dynamodb = boto3.client("dynamodb")

        logger.info(
            "worker starting: version='%s' queue='%s' model='%s' idle_timeout=%is",
            os.getenv("BUILD_VERSION", "unknown"),
            self.queue_url,
            self.model.modelname,
            self.idle_timeout,
        )

    def get_message(self) -> dict | None:
        response = self.client.receive_message(
            QueueUrl=self.queue_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=_LONG_POLL_WAIT,
            VisibilityTimeout=self.visibility_timeout,
        )
        messages = response.get("Messages", [])
        return messages[0] if messages else None

    def process_message(self, msg: dict):
        receipt_handle = msg["ReceiptHandle"]

        try:
            payload = json.loads(msg["Body"])
            sqs_msg = MarigoldSQSMessage.model_validate(payload)
        except (json.JSONDecodeError, ValidationError) as e:
            logger.error("malformed SQS message, discarding [%s]", str(e))
            self.client.delete_message(
                QueueUrl=self.queue_url, ReceiptHandle=receipt_handle
            )
            return

        user_id = sqs_msg.user_id
        message_id = sqs_msg.message_id

        logger.info("[%s/%s] dequeued", user_id, message_id)
        _write_results(sqs_msg, "processing")

        stop_heartbeat = threading.Event()
        heartbeat = threading.Thread(
            target=_heartbeat,
            args=(
                self.client,
                self.queue_url,
                receipt_handle,
                self.visibility_timeout,
                stop_heartbeat,
            ),
            daemon=True,
        )
        heartbeat.start()

        spec = _SPECS.get(sqs_msg.model_type)
        if spec is None:
            stop_heartbeat.set()
            heartbeat.join(timeout=2)
            self.client.delete_message(
                QueueUrl=self.queue_url, ReceiptHandle=receipt_handle
            )
            logger.error(
                "[%s/%s] unknown model_type %r, discarding",
                user_id,
                message_id,
                sqs_msg.model_type,
            )
            return

        request = spec.request_model.model_validate(
            {
                **sqs_msg.model_inputs,
                "model": sqs_msg.model_name,
            }
        )

        logger.info(
            "[%s/%s] submitted %s",
            user_id,
            message_id,
            json.dumps(request.model_dump()),
        )

        try:
            result = self.model.process(user_id, message_id, request)

            if sqs_msg.workflow_execution_id is not None:
                _write_workflow_step_complete(
                    sqs_msg=sqs_msg,
                    output=result.model_dump(),
                )

            _write_results(sqs_msg, "complete", result.model_dump())
            logger.info("[%s/%s] complete", user_id, message_id)

        except ModelNotFoundError as e:
            logger.error(
                "[%s/%s] model not in cache: %s",
                user_id, message_id, str(e),
            )
            if sqs_msg.workflow_execution_id is not None:
                _write_workflow_step_failed(
                    sqs_msg=sqs_msg,
                    error="model not found: %s" % str(e),
                )
            _write_results(sqs_msg, "error", {
                "error": "model not found",
                "model": str(e),
            })

        except Exception as e:
            logger.exception(
                "[%s/%s] processing failed [%s]", user_id, message_id, str(e)
            )
            if sqs_msg.workflow_execution_id is not None:
                _write_workflow_step_failed(
                    sqs_msg=sqs_msg,
                    error=str(e),
                )
            _write_results(sqs_msg, "error", {"error": str(e)})

        finally:
            stop_heartbeat.set()
            heartbeat.join(timeout=2)
            self.client.delete_message(
                QueueUrl=self.queue_url, ReceiptHandle=receipt_handle
            )

    def run(self):
        logger.info(
            "worker starting: queue='%s' model='%s' idle_timeout=%is",
            self.queue_url,
            self.model.modelname,
            self.idle_timeout,
        )

        last_message_at = time.monotonic()

        while True:
            msg = self.get_message()

            if msg is None:
                if time.monotonic() - last_message_at >= self.idle_timeout:
                    logger.info(
                        "idle for %.0fs, exiting",
                        time.monotonic() - last_message_at,
                    )
                    break
                continue

            last_message_at = time.monotonic()
            self.process_message(msg)
