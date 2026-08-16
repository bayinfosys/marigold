"""AWS SQS/SNS messaging backend.

SQSQueueBackend wraps boto3 SQS using the low-level client interface.
SNSNotificationBackend wraps boto3 SNS for fire-and-forget fan-out.

LocalStack compatibility
------------------------
Pass endpoint_url="http://localhost:4566" (or the LocalStack container
hostname) to both backends to use LocalStack instead of real AWS. Credentials
can be any non-empty string when using LocalStack.

SNS subscribe()
---------------
SNS does not support poll-based subscription from Python. subscribe() raises
NotImplementedError. To receive SNS events in Python, subscribe an SQS queue
to the topic and poll that queue with SQSQueueBackend.receive().
"""

import json
import logging

import boto3

from .base import NotificationBackend, QueueBackend

logger = logging.getLogger(__name__)


class SQSQueueBackend(QueueBackend):
    """SQS-backed work queue.

    Queue URLs are resolved from queue names on first use and cached.
    Queues must exist before send() or receive() are called; use
    create_queue() to create them or provision them via Terraform/LocalStack
    setup scripts.

    Args:
        client:       Optional boto3 SQS client. If omitted, one is created
                      using the ambient AWS credentials and region.
        endpoint_url: Optional endpoint override. Pass the LocalStack URL
                      for local development.
    """

    def __init__(self, client=None, endpoint_url: str = None):
        self._client = client or boto3.client("sqs", endpoint_url=endpoint_url)
        self._urls: dict[str, str] = {}

    def _url(self, queue: str) -> str:
        if queue not in self._urls:
            resp = self._client.get_queue_url(QueueName=queue)
            self._urls[queue] = resp["QueueUrl"]
        return self._urls[queue]

    def send(self, queue: str, payload: dict, message_id: str = None) -> str:
        """Enqueue a message. Returns the SQS-assigned message ID.

        Args:
            queue:      Queue name.
            payload:    JSON-serialisable dict. Sent as the SQS MessageBody.
            message_id: Accepted for interface compatibility but not forwarded
                        to SQS on standard queues. SQS generates its own opaque
                        ID. On FIFO queues, pass message_id as
                        MessageDeduplicationId explicitly via the raw client if
                        needed. The SQS-assigned ID is always returned.
        """
        resp = self._client.send_message(
            QueueUrl=self._url(queue),
            MessageBody=json.dumps(payload),
        )
        return resp["MessageId"]

    def receive(self, queue: str, visibility_seconds: int = 300) -> tuple[dict | None, str | None]:
        resp = self._client.receive_message(
            QueueUrl=self._url(queue),
            MaxNumberOfMessages=1,
            WaitTimeSeconds=20,
            VisibilityTimeout=visibility_seconds,
        )
        messages = resp.get("Messages", [])
        if not messages:
            return None, None
        msg = messages[0]
        return json.loads(msg["Body"]), msg["ReceiptHandle"]

    def delete(self, queue: str, receipt_handle: str) -> None:
        self._client.delete_message(
            QueueUrl=self._url(queue),
            ReceiptHandle=receipt_handle,
        )

    def extend_visibility(self, queue: str, receipt_handle: str, visibility_seconds: int) -> None:
        self._client.change_message_visibility(
            QueueUrl=self._url(queue),
            ReceiptHandle=receipt_handle,
            VisibilityTimeout=visibility_seconds,
        )

    def depth(self, queue: str) -> int:
        """Return ApproximateNumberOfMessages for the queue.

        The SQS value is eventually consistent and may not reflect messages
        in flight or very recently enqueued. Use for monitoring only.
        """
        resp = self._client.get_queue_attributes(
            QueueUrl=self._url(queue),
            AttributeNames=["ApproximateNumberOfMessages"],
        )
        return int(resp["Attributes"].get("ApproximateNumberOfMessages", "0"))

    def create_queue(self, queue: str) -> None:
        """Create a standard SQS queue. Idempotent.

        Invalidates the cached URL so the next send/receive resolves
        the new queue URL.
        """
        self._client.create_queue(QueueName=queue)
        self._urls.pop(queue, None)


class SNSNotificationBackend(NotificationBackend):
    """SNS-backed notification bus.

    Topics are resolved to ARNs on first use via create_topic(), which is
    idempotent on SNS. ARNs are cached after the first call.

    Args:
        client:       Optional boto3 SNS client.
        endpoint_url: Optional endpoint override for LocalStack.
    """

    def __init__(self, client=None, endpoint_url: str = None):
        self._client = client or boto3.client("sns", endpoint_url=endpoint_url)
        self._arns: dict[str, str] = {}

    def _arn(self, topic: str) -> str:
        """Resolve topic name to ARN, creating the topic if necessary."""
        if topic not in self._arns:
            resp = self._client.create_topic(Name=topic)
            self._arns[topic] = resp["TopicArn"]
        return self._arns[topic]

    def publish(self, topic: str, payload: dict) -> None:
        self._client.publish(
            TopicArn=self._arn(topic),
            Message=json.dumps(payload),
        )

    def create_topic(self, topic: str) -> None:
        """Create an SNS topic. Idempotent -- returns existing ARN if present."""
        resp = self._client.create_topic(Name=topic)
        self._arns[topic] = resp["TopicArn"]
