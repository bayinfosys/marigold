"""Entry point for the Marigold worker.

local_handler() constructs the Postgres backends and starts the model
scheduler. It is called directly by the container CMD and never
imported transitively.

Environment variables
---------------------
    MARIGOLD_DATABASE_URL           psycopg2 DSN
    MARIGOLD_MODEL_CATALOGUE_TABLE  catalogue table (default: model_catalogue)
    MARIGOLD_RESULTS_TABLE          results table (default: results)
    MARIGOLD_WORKERS_TABLE          workers table (default: workers)
    MARIGOLD_VISIBILITY_TIMEOUT     seconds a claimed message stays
                                    invisible to other workers (default: 300)
    MARIGOLD_QUEUE_IDLE_TIMEOUT     seconds a model stays resident once its
                                    queue empties (default: 0)
    LIFECYCLE_TOPIC                 lifecycle topic name (default: lifecycle)
"""

import logging
import os

from models import load_all as load_all_model_handlers

logger = logging.getLogger(__name__)


def local_handler():
    """Worker entry point.

    Constructs Postgres backends from MARIGOLD_DATABASE_URL and runs a
    ModelScheduler against the model catalogue table, which the cache
    container populates. Creates the results, workers and catalogue
    tables if they do not exist (idempotent); table creation belongs to
    the cache container, and this is the one remaining exception,
    recorded in ARCHITECTURE.md.

    The scheduler reads the catalogue each sweep, so this handler starts
    cleanly against an empty or absent catalogue: it sleeps until rows
    appear, then serves them.

    MARIGOLD_QUEUE_IDLE_TIMEOUT decides how long a model stays resident
    once its queue empties. 0 releases it immediately, which is what one
    GPU serving many models wants. A positive value holds it for that
    many seconds, which suits a small catalogue where reload cost
    dominates. See the note on -1 in QueueRunner before using it.
    """
    from backend.messaging.local import LocalNotificationBackend
    from backend.messaging.postgres import PostgresQueueBackend
    from dynawrap.backends.postgres import PostgresBackend
    from models.worker import ModelScheduler
    from shared.database import get_database_connection
    from shared.results_cache import ResultsCache
    from tools.environment import collect_environment

    load_all_model_handlers()

    visibility_timeout = int(os.getenv("MARIGOLD_VISIBILITY_TIMEOUT", "300"))
    topic = os.getenv("LIFECYCLE_TOPIC", "lifecycle")
    results_table = os.getenv("MARIGOLD_RESULTS_TABLE", "results")
    models_table = os.getenv("MARIGOLD_MODEL_CATALOGUE_TABLE", "model_catalogue")
    workers_table = os.getenv("MARIGOLD_WORKERS_TABLE", "workers")

    conn = get_database_connection()

    queue_backend = PostgresQueueBackend(conn)
    notification_backend = LocalNotificationBackend()

    db_backend = PostgresBackend(conn)

    PostgresBackend.create_table(conn, results_table)
    results_cache = ResultsCache(db_backend, results_table)

    # The cache container creates this on every platform start; creating
    # it here too keeps a worker started by hand from failing its first
    # sweep on a fresh database.
    PostgresBackend.create_table(conn, models_table)

    environment = collect_environment()
    PostgresBackend.create_table(conn, workers_table)
    db_backend.save(workers_table, environment)

    logger.info(
        "worker environment: id='%s' host='%s' cuda=%s devices=%s",
        environment.worker_id, environment.hostname,
        environment.cuda_available, environment.device_names,
    )

    scheduler = ModelScheduler(
        catalogue_backend=db_backend,
        catalogue_table=models_table,
        queue_backend=queue_backend,
        notification_backend=notification_backend,
        visibility_timeout=visibility_timeout,
        topic=topic,
        results_cache=results_cache,
        idle_timeout=int(os.getenv("MARIGOLD_QUEUE_IDLE_TIMEOUT", "0")),
        worker_id=environment.worker_id,
    )

    scheduler.run()
