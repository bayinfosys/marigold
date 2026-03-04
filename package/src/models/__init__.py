"""Model dispatch and SQS worker.

Every ECS task starts with the fixed command:
    python -c "from models import sqs_handler; sqs_handler()"

MODEL_TYPE selects the handler from _SPECS, which is populated by calling
load_all() before use. Call sites that need the full registry must call
load_all() explicitly -- importing this module alone does not trigger handler
imports.

Required environment variables (all tasks):
    MODEL_TYPE              task identifier (e.g. "instruct", "text-eval")
    MODELNAME               HuggingFace model identifier
    AWS_SQS_MODEL_QUEUE     SQS queue URL for this model
    RESULTS_TABLE           DynamoDB results cache table name
    SQS_VISIBILITY_TIMEOUT  matches the queue visibility_timeout_seconds (default 300)

Optional environment variables:
    IDLE_TIMEOUT            seconds to keep polling after queue goes empty (default 0)
    LOG_LEVEL               Python logging level (default INFO)
"""

import json
import logging
import os
import time

import boto3

from shared.outputs import update_results_table
from shared.registry import BaseModelHandler, _SPECS  # noqa: F401

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Registry population
# ---------------------------------------------------------------------------

def load_all():
    """Import all handler modules to populate shared.registry._SPECS.

    Must be called before any code that looks up _SPECS by model type.
    Importing this module alone does not trigger these imports.
    """
    from models import depth, image_embed, image_eval, image_text_eval  # noqa: F401
    from models import img2mask, img2txt, instruct, text_embed           # noqa: F401
    from models import text_eval, text_similarity, tts, txt2img          # noqa: F401
    from models import txt2audio          # noqa: F401


# ---------------------------------------------------------------------------
# SQS worker
# ---------------------------------------------------------------------------

_LONG_POLL_WAIT = 20  # seconds; SQS maximum


class SQSWorker:
    """SQS long-poll loop for any BaseModelHandler.

    Reads one message at a time, calls model.process(), writes the result to
    the DynamoDB results table, then deletes the message.

    On processing failure the error is written to DynamoDB with status "error"
    and the message is deleted, giving the client a terminal state rather than
    leaving them polling indefinitely.

    On malformed messages (unparseable JSON, missing keys) the message is
    logged and deleted immediately to avoid blocking the queue.

    Idle behaviour
    --------------
    When the queue is empty the worker continues polling until idle_timeout
    seconds have elapsed since the last message was processed, then exits.
    Set idle_timeout=0 to exit on the first empty poll response.

    TODO: extend SQS visibility timeout mid-processing for models whose
          inference time approaches visibility_timeout.
    """

    def __init__(
        self,
        queue_url: str,
        model: BaseModelHandler,
        results_table: str,
        visibility_timeout: int,
        idle_timeout: int,
    ):
        self.queue_url = queue_url
        self.model = model
        self.results_table = results_table
        self.visibility_timeout = visibility_timeout
        self.idle_timeout = idle_timeout
        self.client = boto3.client("sqs")

    def _write_status(self, user_id: str, message_id: str, status: str):
        update_results_table(user_id, message_id, self.results_table, {}, status=status)

    def _write_result(self, user_id: str, message_id: str, result: dict):
        update_results_table(
            user_id, message_id, self.results_table, result, status="complete"
        )

    def _write_error(self, user_id: str, message_id: str, message: str):
        try:
            update_results_table(
                user_id,
                message_id,
                self.results_table,
                {"error": message},
                status="error",
            )
        except Exception:
            logger.error(
                "[%s/%s] failed to write error status to DynamoDB", user_id, message_id
            )

    def get_message(self) -> dict | None:
        """Poll SQS once. Returns a single message or None."""
        response = self.client.receive_message(
            QueueUrl=self.queue_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=_LONG_POLL_WAIT,
            VisibilityTimeout=self.visibility_timeout,
        )
        messages = response.get("Messages", [])
        return messages[0] if messages else None

    def process_message(self, msg: dict):
        """Parse and process a single SQS message."""
        receipt_handle = msg["ReceiptHandle"]

        try:
            payload = json.loads(msg["Body"])
            user_id = payload["userid"]
            message_id = payload["message_id"]
            request = payload["request"]
        except (KeyError, json.JSONDecodeError) as e:
            logger.error("malformed SQS message, discarding [%s]", str(e))
            self.client.delete_message(
                QueueUrl=self.queue_url, ReceiptHandle=receipt_handle
            )
            return

        logger.info("[%s/%s] dequeued", user_id, message_id)
        self._write_status(user_id, message_id, "processing")

        try:
            result = self.model.process(user_id, message_id, request)
            self._write_result(user_id, message_id, result.model_dump())
            logger.info("[%s/%s] complete", user_id, message_id)
        except Exception as e:
            logger.exception(
                "[%s/%s] processing failed [%s]", user_id, message_id, str(e)
            )
            self._write_error(user_id, message_id, str(e))
        finally:
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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def sqs_handler():
    """Fixed ECS task entry point for all model types."""
    load_all()

    model_type = os.environ["MODEL_TYPE"]
    modelname = os.environ["MODELNAME"]
    queue_url = os.environ["AWS_SQS_MODEL_QUEUE"]
    results_table = os.environ["RESULTS_TABLE"]
    visibility_timeout = int(os.getenv("SQS_VISIBILITY_TIMEOUT", "300"))
    idle_timeout = int(os.getenv("IDLE_TIMEOUT", "0"))

    if model_type not in _SPECS:
        raise ValueError(
            "unknown MODEL_TYPE '%s'; registered types: %s"
            % (model_type, sorted(_SPECS))
        )

    spec = _SPECS[model_type]
    logger.info("loading '%s' for model '%s'", spec.handler_class.__name__, modelname)

    model = spec.handler_class(modelname)
    worker = SQSWorker(
        queue_url, model, results_table, visibility_timeout, idle_timeout
    )
    worker.run()
