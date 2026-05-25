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
from contextlib import contextmanager
from datetime import datetime, timezone

import boto3
from dynawrap.backends.dynamodb import DynamoDBBackend
from pydantic import ValidationError
from shared.db_models import ResultsItem, WorkflowStep
from shared.registry import _SPECS, BaseModelHandler
from shared.sns_models import EventType, LifecycleEvent
from shared.sqs_models import MarigoldSQSMessage, make_job_id

logger = logging.getLogger(__name__)

_LONG_POLL_WAIT = 20  # seconds; SQS maximum
_HEARTBEAT_BUFFER = 5  # seconds before timeout to extend visibility

DYNAMODB_TABLE = os.environ.get("DYNAMODB_RESULTS_TABLE", "")
IDLE_TIMEOUT = int(os.getenv("IDLE_TIMEOUT", "180"))  # 3 minutes


_ddb = boto3.client("dynamodb")
_dynawrap = DynamoDBBackend(_ddb)


# ---------------------------------------------------------------------------
# Heartbeat
# - for long running messages we update the message visibility in the
# - background to prevent it going back on the queue and starting a new worker
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
        model_hash: str = "",
    ):
        self.queue_url = queue_url
        self.model = model
        self.visibility_timeout = visibility_timeout
        self.idle_timeout = IDLE_TIMEOUT
        self.model_hash = model_hash
        self.model_type = os.environ.get("MODEL_TYPE", "UNSET")
        self.client = boto3.client("sqs")
        self._dynamodb = boto3.client("dynamodb")

        self._base_payload = {
            "model_name": self.model.modelname,
            "model_type": self.model_type,
            "model_hash": self.model_hash,
        }

        logger.info(
            "worker starting: version='%s' queue='%s' model='%s' idle_timeout=%is",
            os.getenv("BUILD_VERSION", "unknown"),
            self.queue_url,
            self.model.modelname,
            self.idle_timeout,
        )

    def _event(
        self, event_type: str, message_id: str = None, payload: dict = None
    ) -> LifecycleEvent:
        return LifecycleEvent(
            event_type=event_type,
            model_name=self.model.modelname,
            model_hash=self.model_hash,
            message_id=message_id,
            payload={**self._base_payload, **(payload or {})},
        )

    @contextmanager
    def _heartbeat_context(self, receipt_handle: str):
        stop = threading.Event()
        thread = threading.Thread(
            target=_heartbeat,
            args=(
                self.client,
                self.queue_url,
                receipt_handle,
                self.visibility_timeout,
                stop,
            ),
            daemon=True,
        )
        thread.start()
        try:
            yield
        finally:
            stop.set()
            thread.join(timeout=2)

    def get_message(self) -> tuple[MarigoldSQSMessage | None, str | None]:
        """Read a message off the queue and parse it."""
        response = self.client.receive_message(
            QueueUrl=self.queue_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=_LONG_POLL_WAIT,
            VisibilityTimeout=self.visibility_timeout,
        )
        messages = response.get("Messages", [])

        if not messages:
            return None, None

        if len(messages) > 1:
            logger.critical("[%s] multiple messages found in queue", self.queue_url)

        msg = messages[0]

        try:
            body = json.loads(msg["Body"])
            sqs_msg = MarigoldSQSMessage.model_validate(body)
        except (json.JSONDecodeError, ValidationError) as e:
            logger.error("malformed SQS message, discarding [%s]", str(e))
            self.client.delete_message(
                QueueUrl=self.queue_url,
                ReceiptHandle=msg["ReceiptHandle"],
            )
            return None, None

        logger.info("[%s/%s] dequeued", sqs_msg.user_id, sqs_msg.message_id)
        self._event(
            EventType.REQUEST_DEQUEUED,
            sqs_msg.message_id,
            payload={"user_id": sqs_msg.user_id},
        ).post()

        return sqs_msg, msg["ReceiptHandle"]

    def process_message(self, sqs_msg: MarigoldSQSMessage):
        self._event(
            EventType.REQUEST_PROCESSING,
            sqs_msg.message_id,
            payload={"user_id": sqs_msg.user_id},
        ).post()

        if sqs_msg.model_type != self.model_type:
            logger.critical(
                "[%s/%s] model routing error [%s!=%s]",
                sqs_msg.user_id,
                sqs_msg.message_id,
                sqs_msg.model_type,
                self.model_type,
            )
            self._event(
                EventType.REQUEST_ERROR,
                sqs_msg.message_id,
                payload={
                    "user_id": sqs_msg.user_id,
                    "error": "model_type_mismatch",
                    "model_type": sqs_msg.model_type,
                    "expected_model_type": self.model_type,
                },
            ).post()
            return

        try:
            spec = _SPECS[sqs_msg.model_type]

            request = spec.request_model.model_validate(
                {**sqs_msg.model_inputs, "model": sqs_msg.model_name}
            )

            logger.info(
                "[%s/%s] submitted %s",
                sqs_msg.user_id,
                sqs_msg.message_id,
                json.dumps(request.model_dump()),
            )

            result = self.model.process(sqs_msg.user_id, sqs_msg.message_id, request)

            if sqs_msg.workflow_execution_id is not None:
                _write_workflow_step_complete(
                    sqs_msg=sqs_msg,
                    output=result.model_dump(),
                )

            self._event(
                EventType.REQUEST_COMPLETE,
                sqs_msg.message_id,
                payload={"user_id": sqs_msg.user_id, "result": result.model_dump()},
            ).post()
            logger.info("[%s/%s] complete", sqs_msg.user_id, sqs_msg.message_id)

        except KeyError as e:
            logger.exception(
                "[%s/%s] unknown model %s [%s]",
                sqs_msg.user_id,
                sqs_msg.message_id,
                sqs_msg.model_name,
                sqs_msg.model_type,
            )
            if sqs_msg.workflow_execution_id is not None:
                _write_workflow_step_failed(sqs_msg=sqs_msg, error=str(e))
            self._event(
                EventType.REQUEST_ERROR,
                sqs_msg.message_id,
                payload={"user_id": sqs_msg.user_id, "error": str(e)},
            ).post()

        except ValidationError as e:
            logger.exception(
                "[%s/%s] malformed message for %s",
                sqs_msg.user_id,
                sqs_msg.message_id,
                sqs_msg.model_type,
            )
            if sqs_msg.workflow_execution_id is not None:
                _write_workflow_step_failed(sqs_msg=sqs_msg, error=str(e))
            self._event(
                EventType.REQUEST_ERROR,
                sqs_msg.message_id,
                payload={"user_id": sqs_msg.user_id, "error": str(e)},
            ).post()

        except Exception as e:
            logger.exception(
                "[%s/%s] processing failed [%s]",
                sqs_msg.user_id,
                sqs_msg.message_id,
                str(e),
            )
            if sqs_msg.workflow_execution_id is not None:
                _write_workflow_step_failed(sqs_msg=sqs_msg, error=str(e))
            self._event(
                EventType.REQUEST_ERROR,
                sqs_msg.message_id,
                payload={"user_id": sqs_msg.user_id, "error": str(e)},
            ).post()

    def run(self):
        logger.info(
            "worker starting: queue='%s' model='%s' idle_timeout=%is",
            self.queue_url,
            self.model.modelname,
            self.idle_timeout,
        )

        self._event(EventType.WORKER_STARTED).post()

        last_message_at = time.monotonic()

        while True:
            sqs_msg, receipt_handle = self.get_message()

            if sqs_msg is None:
                idle_s = time.monotonic() - last_message_at

                if self.idle_timeout == 0 or idle_s >= self.idle_timeout:
                    self._event(EventType.WORKER_EXITING).post()
                    logger.info("idle for %.0fs, exiting", idle_s)
                    break

                self._event(EventType.WORKER_IDLE).post()
                continue

            try:
                with self._heartbeat_context(receipt_handle):
                    self.process_message(sqs_msg)
            except Exception as e:
                logger.exception(
                    "[%s] message failed [%s]",
                    self.model.modelname,
                    str(e),
                )
            finally:
                self.client.delete_message(
                    QueueUrl=self.queue_url,
                    ReceiptHandle=receipt_handle,
                )

            last_message_at = time.monotonic()
