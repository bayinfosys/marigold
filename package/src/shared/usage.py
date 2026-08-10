"""Usage tracking and metrics.

record_usage() is the single call site for all handler modules. It
builds a ModelUsageStats, writes to the usage table, and returns the
stats for inclusion in the handler response.
"""

import logging
import os

import psycopg2
from dynawrap.backends.postgres import PostgresBackend

from shared.enums import ModelType
from shared.usage_models import ModelUsageStats, UsageItem

logger = logging.getLogger(__name__)

_dynawrap = None


def _get_backend():
    """Lazily connect on first use.

    Deliberately not connected at import time: usage.py is imported by
    every handler module, which means it is also imported during
    cache-init's models.load_all() call -- before Postgres exists in
    the compose startup order. write_usage() is never actually called
    from that path, so the connection only needs to succeed once a
    real inference request needs to record usage.
    """
    global _dynawrap
    if _dynawrap is None:
        dsn = os.environ["MARIGOLD_DATABASE_URL"]
        conn = psycopg2.connect(dsn)
        conn.autocommit = True
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
