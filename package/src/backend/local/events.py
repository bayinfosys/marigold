"""No-op notification backend for local development."""

import logging
from .base import NotificationBackend

logger = logging.getLogger(__name__)


class LocalNotificationBackend(NotificationBackend):
    def publish(self, topic: str, payload: dict) -> None:
        logger.debug("event: %s", payload.get("event_type"))

    def create_topic(self, topic: str) -> None:
        pass
