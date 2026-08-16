"""AWS SNS event bus.

Publishes LifecycleEvent instances to the configured SNS topic.
Replaces the boto3 call embedded in LifecycleEvent.post().
"""

import logging
import os

import boto3

from shared.schedule_models import LifecycleEvent

logger = logging.getLogger(__name__)

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = boto3.client("sns")
    return _client


class SNSEventBus:
    """Publishes LifecycleEvent to an SNS topic."""

    def __init__(self, topic_arn: str | None = None):
        self.topic_arn = topic_arn or os.environ.get("LIFECYCLE_TOPIC_ARN", "")

    def publish(self, event: LifecycleEvent) -> None:
        if not self.topic_arn:
            return
        try:
            _get_client().publish(**event.to_sns_kwargs(self.topic_arn))
        except Exception as e:
            logger.warning("failed to publish %s: %s", event.event_type, e)
