"""Marigold API -- FastAPI application entry point.

On AWS
------
API Gateway intercepts every request at the integration layer using the
AWS-specific decorator metadata on each route. The FastAPI function bodies
never execute. The lifespan hook detects the Lambda environment and skips
backend construction entirely.

The openapi.json produced by this app is uploaded to S3 and used by
Terraform to configure API Gateway integrations. Generate it with:

    python3 -m api.export_openapi > assets/openapi.json

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
    MODELS_CONFIG_PATH        path to models_config.json (local)
    MODELS_CONFIG_S3_OBJECT   S3 key for models_config.json (AWS)
    AWS_S3_ASSETS_BUCKET_NAME S3 bucket (AWS)
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

from models.catalogue import load_catalogue_from_yaml, save_models

from api.routes import router

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s:%(name)s:%(message)s",
    force=True,
)

logger = logging.getLogger(__name__)


def _is_lambda() -> bool:
    return bool(os.getenv("AWS_EXECUTION_ENV") or os.getenv("AWS_LAMBDA_FUNCTION_NAME"))


def _build_local_backends(app: FastAPI) -> None:
    import psycopg2
    from dynawrap.backends.postgres import PostgresBackend
    from backend.messaging.postgres import PostgresQueueBackend
    from backend.messaging.local import LocalNotificationBackend
    from tools.polling.results_cache import ResultsCache

    dsn = os.environ["MARIGOLD_DATABASE_URL"]
    results_table = os.environ["MARIGOLD_RESULTS_TABLE"]
    model_catalogue_table = os.environ["MARIGOLD_MODEL_CATALOGUE_TABLE"]
    model_catalogue_yamls = os.environ["MARIGOLD_MODEL_CATALOGUE_YAMLS"]

    conn = psycopg2.connect(dsn)
    conn.autocommit = True

    queue_backend = PostgresQueueBackend(conn)
    notification_backend = LocalNotificationBackend()

    # create the output results
    table_backend = PostgresBackend(conn)
    PostgresBackend.create_table(conn, results_table)
    results_cache = ResultsCache(table_backend, results_table)

    # create the model catalogue
    model_catalogue_items = load_catalogue_from_yaml(list(glob.glob(model_catalogue_yamls)))
    logger.info("found %i models", len(model_catalogue_items))
    PostgresBackend.create_table(conn, model_catalogue_table)
    save_models(table_backend, model_catalogue_table, model_catalogue_items)

    # set application state for the api
    app.state.queue_backend = queue_backend
    app.state.notification_backend = notification_backend
    app.state.results_cache = results_cache
    app.state.table_backend = table_backend
    app.state.topic = os.getenv("LIFECYCLE_TOPIC", "lifecycle")
    app.state.model_catalogue_table = model_catalogue_table

    logger.info(
        "local backends configured: %d models, models='%s', results='%s'",
        len(model_catalogue_items),
        model_catalogue_table,
        results_table,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    if _is_lambda():
        logger.info("Lambda environment detected -- skipping backend construction")
        app.state.queue_backend = None
        app.state.notification_backend = None
        app.state.results_cache = None
        app.state.topic = None
    elif os.getenv("MARIGOLD_DATABASE_URL"):
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
