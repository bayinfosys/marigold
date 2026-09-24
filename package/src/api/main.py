"""Marigold API -- FastAPI application entry point.

Locally
-------
uvicorn runs this app directly. The lifespan hook constructs Postgres
backends from DATABASE_URL and wires them into app.state. Route handlers
call receiver_logic functions via app.state, giving a complete local
replica of the submission and polling paths.

    uvicorn api.main:app --reload --port 8000

Environment variables
---------------------
Both:
    LIFECYCLE_TOPIC           notification topic name (default: lifecycle)
    RESULTS_TABLE             results cache table name

Local only:
    DATABASE_URL              psycopg2 DSN
"""

import logging
import os
import glob
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from models.catalogue import load_catalogue_from_yaml
from shared.database import get_database_connection

from api.routes import router

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s:%(name)s:%(message)s",
    force=True,
)

logger = logging.getLogger(__name__)


def _build_local_backends(app: FastAPI) -> None:
    """Connect to Postgres and wire backends into app.state.

    The API reads the catalogue; it never loads models.yaml. Catalogue
    rows and their queues are written by the cache container, for the
    models present in the cache.
    """
    from dynawrap.backends.postgres import PostgresBackend
    from backend.messaging.postgres import PostgresQueueBackend
    from backend.messaging.local import LocalNotificationBackend
    from shared.results_cache import ResultsCache

    results_table = os.environ["MARIGOLD_RESULTS_TABLE"]
    model_catalogue_table = os.environ["MARIGOLD_MODEL_CATALOGUE_TABLE"]

    conn = get_database_connection()

    # create the tables
    table_backend = PostgresBackend(conn)
    PostgresBackend.create_table(conn, results_table)
    PostgresBackend.create_table(conn, model_catalogue_table)
    PostgresBackend.create_table(conn, os.getenv("MARIGOLD_USAGE_TABLE", "usage"))

    # create the queues
    app.state.queue_backend = PostgresQueueBackend(conn)
    app.state.notification_backend = LocalNotificationBackend()
    app.state.results_cache = ResultsCache(table_backend, results_table)
    app.state.table_backend = table_backend
    app.state.topic = os.getenv("LIFECYCLE_TOPIC", "lifecycle")
    app.state.model_catalogue_table = model_catalogue_table

    logger.info(
        "local backends configured: models='%s', results='%s'",
        model_catalogue_table,
        results_table,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    if os.getenv("MARIGOLD_DATABASE_URL"):
        _build_local_backends(app)
    else:
        logger.critical("neither Lambda environment nor MARIGOLD_DATABASE_URL detected")
        raise ValueError("MARIGOLD_DATABASE_URL expected")

    yield


app = FastAPI(
    title="Marigold",
    description="Hosted model inference API.",
    version=os.getenv("MARIGOLD_VERSION", "dev"),
    lifespan=lifespan,
)

app.include_router(router)


@app.exception_handler(Exception)
async def unhandled_exception(request, exc):
    logger.exception("unhandled exception: %s", exc)
    return JSONResponse(status_code=500, content={"status": "error", "message": "internal error"})
