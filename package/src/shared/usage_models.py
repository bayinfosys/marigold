"""Usage records.

UsageItem is one row in the usage table: a billable or measurable event,
written once and never updated. ModelUsageStats, the inference-level
facts, is defined in api.models and carried here as model_stats.
"""

from datetime import datetime, timezone
from typing import ClassVar, Optional

from dynawrap import DBItem
from pydantic import BaseModel

from api.models import ModelUsageStats


class UsageItem(DBItem, BaseModel):
    """One record in the usage table.

    model_stats is populated for inference requests and null for other
    event types as those are added.

    The sort key ends in the message id. recorded_at has one-second
    resolution, so two requests from one user to one model within the
    same second share every other segment; without the message id the
    second write would replace the first. Queries by date or operation
    are prefix queries and are unaffected.

    Written once per event. Never updated.
    """

    pk_pattern: ClassVar[str] = "METRIC#RAW#USER#{user_id}"
    sk_pattern: ClassVar[str] = "DATE#{recorded_at}#OP#{operation}#MSG#{message_id}"

    user_id:      str
    recorded_at:  str              # UTC, YYYYmmddTHHMMSSZ
    operation:    str              # event type, e.g. "instruct/qwen2-0.5b"
    message_id:   str = ""         # the request this records; empty for non-request events
    model_stats:  Optional[ModelUsageStats] = None

    @classmethod
    def make_recorded_at(cls) -> str:
        return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    @classmethod
    def from_model_stats(
        cls,
        stats: ModelUsageStats,
        user_id: str,
        model_type: str,
        model_name: str,
        message_id: str,
    ) -> "UsageItem":
        return cls(
            user_id=user_id,
            recorded_at=cls.make_recorded_at(),
            operation="%s/%s" % (model_type, model_name),
            message_id=message_id,
            model_stats=stats,
        )
