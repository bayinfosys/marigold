"""PostgreSQL queue and notification backend.

Queue: one table per queue using SELECT FOR UPDATE SKIP LOCKED.
Notifications: LISTEN/NOTIFY with a durable outbox table for at-least-once
delivery.

Connection management
---------------------
PostgresQueueBackend accepts a psycopg2 connection. Connection lifecycle
is the caller's responsibility. Each operation opens a cursor, executes,
and commits immediately.

PostgresNotificationBackend accepts a DSN string. It manages two internal
connections: one for publish() (transactional) and one per listen() call
(autocommit, dedicated to LISTEN). The outbox repeater runs a third
connection on a background thread.

Topic names
-----------
Topic names are used as Postgres NOTIFY/LISTEN channel identifiers and
must be valid Postgres identifiers. quote_ident() is applied automatically.
"""

import hashlib
import json
import logging
import time

import psycopg2
import psycopg2.extensions
import psycopg2.extras

from .base import QueueBackend

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ID generation
# ---------------------------------------------------------------------------


def _default_message_id(queue: str, payload: dict) -> str:
    """Generate a message ID from queue name, payload, and current time.

    The monotonic nanosecond timestamp ensures uniqueness for identical
    payloads sent in rapid succession. md5 is used for a compact hex
    string readable in logs and the results table.
    """
    content = (
        queue
        + ":"
        + str(time.monotonic_ns())
        + ":"
        + json.dumps(payload, sort_keys=True)
    )
    return hashlib.md5(content.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------------


class PostgresQueueBackend(QueueBackend):
    """Work queue backed by a Postgres table per queue.

    Each queue is a table named queue_{name}. Messages are dequeued with
    SELECT FOR UPDATE SKIP LOCKED so concurrent workers never receive the
    same message.

    Visibility timeout is implemented as a visible_at column. A message
    whose visible_at is in the past is eligible for dequeue. On receive(),
    visible_at is advanced by visibility_seconds. The caller must call
    delete() on success or let the timeout lapse for automatic redelivery.
    extend_visibility() resets the clock from a heartbeat thread.

    Args:
        conn:         psycopg2 connection. Lifecycle is the caller's
                      responsibility.
        id_generator: Optional callable(queue: str, payload: dict) -> str.
                      Defaults to _default_message_id. Supply a custom
                      generator to embed application job IDs.
    """

    def __init__(self, conn, id_generator=None):
        self._conn = conn
        self._id_generator = id_generator or _default_message_id

    def _table(self, queue: str) -> str:
        return f"queue_{queue.replace('-', '_')}"

    def create_queue(self, queue: str) -> None:
        """Create the queue table and indexes. Idempotent."""
        t = self._table(queue)
        with self._conn.cursor() as cur:
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {t} (
                    id          BIGSERIAL PRIMARY KEY,
                    message_id  TEXT NOT NULL,
                    payload     JSONB NOT NULL,
                    visible_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
                    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_{t}_message_id
                    ON {t} (message_id);
                CREATE INDEX IF NOT EXISTS idx_{t}_visible_at
                    ON {t} (visible_at);
            """)
        self._conn.commit()

    def send(self, queue: str, payload: dict, message_id: str = None) -> str:
        """Enqueue a message. Returns the message ID."""
        t = self._table(queue)
        mid = message_id or self._id_generator(queue, payload)
        with self._conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO {t} (message_id, payload) VALUES (%s, %s)",
                (mid, json.dumps(payload)),
            )
        self._conn.commit()
        return mid

    def receive(
        self, queue: str, visibility_seconds: int = 300
    ) -> tuple[dict | None, str | None]:
        """Dequeue one message using SKIP LOCKED.

        Returns (payload, receipt_handle) or (None, None) if empty.
        receipt_handle is the row's BIGSERIAL id as a string.
        """
        t = self._table(queue)
        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                f"""
                UPDATE {t}
                SET visible_at = now() + interval '{visibility_seconds} seconds'
                WHERE id = (
                    SELECT id FROM {t}
                    WHERE visible_at <= now()
                    ORDER BY id
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                RETURNING id, message_id, payload
                """,
            )
            row = cur.fetchone()
        self._conn.commit()

        if row is None:
            return None, None

        payload = (
            row["payload"]
            if isinstance(row["payload"], dict)
            else json.loads(row["payload"])
        )
        return payload, str(row["id"])

    def delete(self, queue: str, receipt_handle: str) -> None:
        t = self._table(queue)
        with self._conn.cursor() as cur:
            cur.execute(f"DELETE FROM {t} WHERE id = %s", (int(receipt_handle),))
        self._conn.commit()

    def extend_visibility(
        self, queue: str, receipt_handle: str, visibility_seconds: int
    ) -> None:
        t = self._table(queue)
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {t}
                SET visible_at = now() + interval '{visibility_seconds} seconds'
                WHERE id = %s
                """,
                (int(receipt_handle),),
            )
        self._conn.commit()

    def depth(self, queue: str) -> int:
        """Return the count of visible (not in-flight) messages."""
        t = self._table(queue)
        with self._conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {t} WHERE visible_at <= now()")
            return cur.fetchone()[0]
