"""shared/database.py -- connections to the platform database.

The single place a Postgres connection is opened. Callers wrap the
connection in whatever they need (a dynawrap PostgresBackend, a
PostgresQueueBackend); none of them import psycopg2 to get one.
"""

import logging
import os
import time

import psycopg2

logger = logging.getLogger(__name__)


class DatabaseUnavailable(Exception):
    """The platform database could not be reached, or is not configured."""


def get_database_connection(
    dsn: str | None = None,
    retries: int = 0,
    interval: float = 5.0,
):
    """Open an autocommit connection to the platform database.

    dsn defaults to MARIGOLD_DATABASE_URL. retries > 0 waits for a
    database still starting, which is the case for any container
    started in a different compose project from Postgres.

    Autocommit matches every existing caller, and means a failed
    statement does not leave the connection in an aborted transaction.
    """
    dsn = dsn or os.environ.get("MARIGOLD_DATABASE_URL")

    if not dsn:
        raise DatabaseUnavailable("MARIGOLD_DATABASE_URL is not set")

    attempt = 0

    while True:
        try:
            conn = psycopg2.connect(dsn)
            conn.autocommit = True
            return conn

        except psycopg2.OperationalError as e:
            if attempt >= retries:
                raise DatabaseUnavailable(str(e)) from e

            attempt += 1
            logger.info(
                "database unavailable, retry %d/%d in %.0fs", attempt, retries, interval
            )
            time.sleep(interval)
