"""Base interfaces for queue and notification backends.

All backends inherit from QueueBackend or NotificationBackend and implement
every method. The interfaces define the contract; implementations are free to
use any underlying transport (SQS/SNS, Postgres, SQLite, etc.).

Queue semantics
---------------
Point-to-point: one message is delivered to exactly one consumer.
Messages are not removed until the consumer calls delete(). If the consumer
does not call delete() before the visibility timeout expires, the message
becomes visible again and another consumer may receive it.

Notification semantics
----------------------
Publish/subscribe: one message is delivered to all current subscribers.
No delivery guarantee to subscribers that are not listening at publish time
unless the backend implements a durable outbox (see PostgresNotificationBackend).
"""


class QueueBackend:
    """Interface for a point-to-point work queue.

    One message is delivered to exactly one consumer.
    Messages are not deleted until explicitly acknowledged.
    """

    def send(self, queue: str, payload: dict, message_id: str = None) -> str:
        """Enqueue a message. Returns the message ID.

        Args:
            queue:      Queue name. Must have been created with create_queue().
            payload:    Arbitrary JSON-serialisable dict.
            message_id: Optional caller-supplied ID. If omitted the backend
                        generates one. Supplying the application job ID here
                        ties the queue record to downstream results table
                        entries without any extra lookup.

        Returns:
            The message ID -- either the supplied value or the backend-generated
            one. Callers that need to correlate with results should capture this.
        """
        raise NotImplementedError

    def receive(self, queue: str, visibility_seconds: int = 300) -> tuple[dict | None, str | None]:
        """Dequeue one message.

        Returns (payload, receipt_handle) or (None, None) if the queue is
        empty. The message is hidden from other consumers for visibility_seconds.
        The caller must call delete() on success or allow the timeout to expire
        for automatic redelivery. extend_visibility() resets the clock.

        Args:
            queue:              Queue name.
            visibility_seconds: How long to hide the message from other
                                consumers. Should match the expected processing
                                time with headroom. Default: 300.

        Returns:
            (payload dict, receipt_handle str) or (None, None).
        """
        raise NotImplementedError

    def delete(self, queue: str, receipt_handle: str) -> None:
        """Permanently remove a message after successful processing.

        Args:
            queue:          Queue name.
            receipt_handle: Value returned by receive().
        """
        raise NotImplementedError

    def extend_visibility(self, queue: str, receipt_handle: str, visibility_seconds: int) -> None:
        """Reset the visibility timeout on an in-flight message.

        Call periodically from a heartbeat thread when processing may exceed
        the original visibility_seconds supplied to receive().

        Args:
            queue:              Queue name.
            receipt_handle:     Value returned by receive().
            visibility_seconds: New timeout from now.
        """
        raise NotImplementedError

    def depth(self, queue: str) -> int:
        """Return the number of visible (not in-flight) messages.

        The value is approximate on backends where counting is non-atomic
        (e.g. SQS). Use for monitoring and queue selection, not for flow
        control.

        Args:
            queue: Queue name.
        """
        raise NotImplementedError

    def create_queue(self, queue: str) -> None:
        """Create the queue if it does not exist. Idempotent.

        Args:
            queue: Queue name.
        """
        raise NotImplementedError


class NotificationBackend:
    """Interface for a publish/subscribe notification bus.

    One message is delivered to all current subscribers. Subscribers that
    are not listening at publish time may miss the message unless the backend
    implements a durable outbox.
    """

    def publish(self, topic: str, payload: dict) -> None:
        """Publish a message to all subscribers of topic.

        Args:
            topic:   Topic name. Must have been created with create_topic().
            payload: Arbitrary JSON-serialisable dict.
        """
        raise NotImplementedError

    def create_topic(self, topic: str) -> None:
        """Create the topic if it does not exist. Idempotent.

        Args:
            topic: Topic name.
        """
        raise NotImplementedError
