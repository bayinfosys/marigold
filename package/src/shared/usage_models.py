"""Usage tracking and metrics.

ModelUsageStats is defined here rather than in api/models.py so that
handler modules and shared infrastructure can import it without depending
on the API layer.
"""

from datetime import datetime, timezone


from pydantic import BaseModel
from dynawrap import DBItem
from typing import Optional, ClassVar

from api.models import ModelUsageStats

# ---------------------------------------------------------------------------
# Usage stats model
# ---------------------------------------------------------------------------


class UsageItem(DBItem, BaseModel):
    """One billing record in the usage table.

    Captures the full context of a billable platform event. model_stats
    is populated for inference requests and null for other event types
    (API key operations, data retrieval, etc.) as those billing dimensions
    are added.

    Written once per billable event. Never updated.
    """

    pk_pattern: ClassVar[str] = "METRIC#RAW#USER#{user_id}"
    sk_pattern: ClassVar[str] = "DATE#{recorded_at}#OP#{operation}"

    user_id:      str
    recorded_at:  str              # UTC, YYYYmmddTHHMMSSZ
    operation:    str              # event type, e.g. "instruct/qwen2-0.5b"
    model_stats:  Optional[ModelUsageStats] = None
    # Future billing dimensions added here as Optional fields:
    # api_calls:    Optional[int] = None
    # bytes_read:   Optional[int] = None

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
    ) -> "UsageItem":
        return cls(
            user_id=user_id,
            recorded_at=cls.make_recorded_at(),
            operation="%s/%s" % (model_type, model_name),
            model_stats=stats,
        )
