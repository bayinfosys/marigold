"""AWS SQS message transport.

Receive, delete, and depth-check operations for a single queue URL.
"""

import json
import logging

import boto3
from botocore.exceptions import NoRegionError
from pydantic import ValidationError

from shared.schedule_models import MarigoldMessage

logger = logging.getLogger(__name__)

_LONG_POLL_WAIT = 20


class SQSQueue:
    """Thin wrapper around a single SQS queue URL."""

    def __init__(self, queue_url: str, visibility_timeout: int = 600):
        self.queue_url = queue_url
        self.visibility_timeout = visibility_timeout
        self._client = boto3.client("sqs")

    def receive(self) -> tuple[MarigoldMessage | None, str | None]:
        """Read one message. Returns (parsed_message, receipt_handle) or (None, None)."""
        response = self._client.receive_message(
            QueueUrl=self.queue_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=_LONG_POLL_WAIT,
            VisibilityTimeout=self.visibility_timeout,
        )
        messages = response.get("Messages", [])
        if not messages:
            return None, None

        msg = messages[0]
        try:
            body = json.loads(msg["Body"])
            sqs_msg = MarigoldMessage.model_validate(body)
        except (json.JSONDecodeError, ValidationError) as e:
            logger.error("malformed SQS message, discarding [%s]", str(e))
            self.delete(msg["ReceiptHandle"])
            return None, None

        return sqs_msg, msg["ReceiptHandle"]

    def delete(self, receipt_handle: str) -> None:
        self._client.delete_message(
            QueueUrl=self.queue_url,
            ReceiptHandle=receipt_handle,
        )

    def extend_visibility(self, receipt_handle: str, timeout: int) -> None:
        self._client.change_message_visibility(
            QueueUrl=self.queue_url,
            ReceiptHandle=receipt_handle,
            VisibilityTimeout=timeout,
        )

    def depth(self) -> int:
        """Return ApproximateNumberOfMessages for this queue."""
        try:
            resp = self._client.get_queue_attributes(
                QueueUrl=self.queue_url,
                AttributeNames=["ApproximateNumberOfMessages"],
            )
            return int(resp["Attributes"].get("ApproximateNumberOfMessages", "0"))
        except Exception as e:
            logger.warning("failed to get depth for %s: %s", self.queue_url, e)
            return 0
