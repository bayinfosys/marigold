"""Usage tracking and metrics.

record_usage() is the single call site for all handler modules. It
builds a ModelUsageStats, writes to the usage table, and returns the
stats for inclusion in the handler response. model_usage_summary()
reads back every row recorded for one model.
"""

import logging
import math
import os

from dynawrap.backends.postgres import PostgresBackend

from marigold.shared.schemas import ModelUsageStats
from marigold.shared.usage_models import UsageItem
from marigold.shared.database import get_database_connection

logger = logging.getLogger(__name__)

_dynawrap = None


def _get_backend():
    """Lazily connect on first use.

    Deliberately not connected at import time: usage.py is imported by
    every handler module, which means it is also imported during
    cache-init's marigold.models.load_all() call -- before Postgres exists in
    the compose startup order. write_usage() is never actually called
    from that path, so the connection only needs to succeed once a
    real inference request needs to record usage.
    """
    global _dynawrap
    if _dynawrap is None:
        conn = get_database_connection()
        _dynawrap = PostgresBackend(conn)
    return _dynawrap


def build_usage(
    user_id: str,
    model_type: str,
    modelname: str,
    duration: float,
    inference: float,
    input_tokens: int = 0,
    output_tokens: int = 0,
    load_time_ms: int = 0,
    model_size_bytes: int = 0,
) -> ModelUsageStats:
    """Model-level usage facts only. System-level facts (VRAM, power,
    process memory, CPU offload) are filled in by the caller after
    this returns -- see PowerSampler.as_usage_fields()."""
    return ModelUsageStats(
        duration=int(duration * 1000),
        inference=int(inference * 1000),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        load_time_ms=load_time_ms,
        model_size_bytes=model_size_bytes,
    )


def write_usage(item: UsageItem) -> None:
    """The save half of what record_usage() used to do in one step."""
    update_metrics(item)


def update_metrics(item: UsageItem):
    table = os.getenv("MARIGOLD_USAGE_TABLE", "usage")
    try:
        _get_backend().save(table, item)
    except Exception as e:
        logger.exception(
            "[%s/%s] failed to write metrics to '%s' [%s]",
            item.user_id, item.operation, table, str(e),
        )


def summarise_usage(stats: list[ModelUsageStats]) -> dict:
    """Totals, percentiles, means and peaks over a model's usage rows.

    Percentiles are nearest-rank over each request's total duration.
    Power is the mean of each request's mean draw, and the highest peak.
    """
    if not stats:
        return {"requests": 0}

    durations = sorted(s.duration for s in stats)

    def percentile(p: int) -> int:
        return durations[max(0, math.ceil(p / 100 * len(durations)) - 1)]

    return {
        "requests": len(stats),
        "input_tokens": sum(s.input_tokens for s in stats),
        "output_tokens": sum(s.output_tokens for s in stats),
        "duration_ms": {"p50": percentile(50), "p90": percentile(90), "p99": percentile(99)},
        "load_time_ms_mean": sum(s.load_time_ms for s in stats) / len(stats),
        "vram_bytes_peak": max(s.vram_usage_bytes_peak for s in stats),
        "power_watts_mean": sum(s.power_watts_mean for s in stats) / len(stats),
        "power_watts_peak": max(s.power_watts_peak for s in stats),
    }


def model_usage_summary(conn, table: str, model_type: str, model_name: str) -> dict:
    """Summarise every usage row recorded for one model.

    Usage rows are keyed by user, so a model's rows are found by their
    operation, which reads the whole table: suited to one host's usage.
    """
    operation = "%s/%s" % (model_type, model_name)

    with conn.cursor() as cursor:
        cursor.execute(
            f"SELECT data->'model_stats' FROM {table} WHERE data->>'operation' = %s",
            (operation,),
        )
        rows = cursor.fetchall()

    return summarise_usage(
        [ModelUsageStats.model_validate(row[0]) for row in rows if row[0]]
    )
