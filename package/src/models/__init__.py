"""Model dispatch registry and generic SQS entry point.

Every ECS task starts with the fixed command:
    python -c "from models import sqs_handler; sqs_handler()"

MODEL_TYPE selects the handler class from the registry below.
No handler path is stored in models.yaml or Terraform.

Required environment variables (all tasks):
    MODEL_TYPE              model category (e.g. "instruct", "text-embedding")
    MODELNAME               HuggingFace model identifier
    AWS_SQS_MODEL_QUEUE     SQS queue URL for this model
    RESULTS_TABLE           DynamoDB results cache table name or ARN
    SQS_VISIBILITY_TIMEOUT  matches the queue visibility_timeout_seconds (default 300)

Optional environment variables:
    IDLE_TIMEOUT            seconds to keep polling after the queue goes empty (default 0)
                            set to a positive value to amortise cold-start cost across
                            bursts of requests; use ~600 for GPU tasks, ~3600 for CPU tasks
    LOG_LEVEL               Python logging level (default INFO)
"""

import importlib
import json
import logging
import os
import time

import boto3
from shared import update_results_table

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Registry
#
# Maps MODEL_TYPE -> (module_path, class_name).
# The named class must be a subclass of BaseModelHandler.
# ---------------------------------------------------------------------------

_REGISTRY = {
    "instruct": ("models.instruct", "InstructModel"),
    "text-embedding": ("models.text_embed", "TextEmbeddingModel"),
    "image-embedding": ("models.image_embed", "ImageEmbeddingModel"),
    "tts": ("models.tts", "TTSModel"),
    "depth": ("models.depth", "DepthModel"),
    "img2txt": ("models.img2txt", "Img2TxtModel"),
    "txt2img": ("models.txt2img", "Txt2ImgModel"),
    "img2mask": ("models.img2mask", "Img2MaskModel"),
}


# ---------------------------------------------------------------------------
# Base handler
# ---------------------------------------------------------------------------


class BaseModelHandler:
    """Base class for all model handlers.

    Subclasses must implement process(). The SQSWorker calls process() with
    the raw request dict from the SQS message body and expects a Pydantic
    BaseModel instance in return.

    Model loading (from EFS cache) should happen in __init__ so it occurs
    once at task start, not per message.
    """

    def __init__(self, modelname: str):
        self.modelname = modelname

    def process(self, user_id: str, message_id: str, request: dict):
        """Process one inference request.

        :param user_id:    authenticated user identifier
        :param message_id: unique request identifier
        :param request:    raw request dict from the SQS message body
        :returns:          a Pydantic BaseModel instance
        """
        raise NotImplementedError


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
    seconds have elapsed since the last message, then exits. Set idle_timeout=0
    to exit immediately on the first empty response.

    Suggested values (set per-model in models.yaml via IDLE_TIMEOUT):
        GPU tasks (instruct, txt2img, depth, img2txt):   600  (10 minutes)
        CPU tasks (text-embedding, image-embedding):    3600  (1 hour)
        TTS (CPU, moderate cost):                        600

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

    # -- DynamoDB writes -----------------------------------------------------

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

    # -- Message handling ----------------------------------------------------

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

    # -- Run loop ------------------------------------------------------------

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
    """Fixed ECS task entry point for all model types.

    Dispatches to the appropriate handler class via _REGISTRY, keyed on
    the MODEL_TYPE environment variable set by Terraform.
    """
    model_type = os.environ["MODEL_TYPE"]
    modelname = os.environ["MODELNAME"]
    queue_url = os.environ["AWS_SQS_MODEL_QUEUE"]
    results_table = os.environ["RESULTS_TABLE"]
    visibility_timeout = int(os.getenv("SQS_VISIBILITY_TIMEOUT", "300"))
    idle_timeout = int(os.getenv("IDLE_TIMEOUT", "0"))

    if model_type not in _REGISTRY:
        raise ValueError(
            "unknown MODEL_TYPE '%s'; registered types: %s"
            % (model_type, sorted(_REGISTRY))
        )

    module_path, class_name = _REGISTRY[model_type]

    logger.info(
        "loading handler '%s.%s' for model '%s'", module_path, class_name, modelname
    )
    module = importlib.import_module(module_path)
    model_class = getattr(module, class_name)
    model = model_class(modelname)

    worker = SQSWorker(
        queue_url, model, results_table, visibility_timeout, idle_timeout
    )
    worker.run()
