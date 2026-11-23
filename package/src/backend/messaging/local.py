"""Notification backend that stores lifecycle events.

Each event published becomes a WorkerEvent row in the events table,
keyed by model and ordered by time. No network calls and no threads:
the publisher's own table backend writes the row.
"""

import logging

from dynawrap.backends.base import DBBackend

from shared.db_models import WorkerEvent
from shared.schedule_models import LifecycleEvent

from shared.messaging import NotificationBackend

logger = logging.getLogger(__name__)


class LocalNotificationBackend(NotificationBackend):
    """Notification backend that saves each event as a WorkerEvent row.

    Args:
        table_backend: DBBackend holding the events table.
        table:         Events table name.
    """

    def __init__(self, table_backend: DBBackend, table: str):
        self.table_backend = table_backend
        self.table = table

    def publish(self, topic: str, payload: dict) -> None:
        event = LifecycleEvent.model_validate(payload)
        self.table_backend.save(self.table, WorkerEvent.from_lifecycle_event(event))
        logger.debug("event: %s", event.event_type)

    def create_topic(self, topic: str) -> None:
        pass
