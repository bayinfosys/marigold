"""No-op notification backend for local development.

Logs lifecycle events at DEBUG level. No network calls, no threads,
no database tables. Used in place of SNSNotificationBackend locally
so the worker can publish events without any AWS dependency.
"""

import logging

from .base import NotificationBackend

logger = logging.getLogger(__name__)


class LocalNotificationBackend(NotificationBackend):
    """Notification backend that logs events and does nothing else."""

    def publish(self, topic: str, payload: dict) -> None:
        logger.debug("event: %s", payload.get("event_type"))

    def create_topic(self, topic: str) -> None:
        pass
