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
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from api.routes import router

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s:%(name)s:%(message)s",
    force=True,
)

logger = logging.getLogger(__name__)


def _is_lambda() -> bool:
    return bool(os.getenv("AWS_EXECUTION_ENV") or os.getenv("AWS_LAMBDA_FUNCTION_NAME"))


def _load_models_config() -> dict:
    """Load models_config.json from S3 or local filesystem.

    Delegates to the same loader used by entrypoint_handlers so the
    resolution logic is defined in one place.
    """
    from models.entrypoint_handlers import _load_models_config as _load
    return _load()




def _build_local_backends(app: FastAPI) -> None:
    import psycopg2
    from dynawrap.backends.postgres import PostgresBackend
    from backend.messaging.postgres import PostgresQueueBackend
    from backend.messaging.local import LocalNotificationBackend
    from tools.polling.results_cache import ResultsCache

    dsn = os.environ["DATABASE_URL"]
    results_table = os.environ["RESULTS_TABLE"]

    conn = psycopg2.connect(dsn)
    conn.autocommit = True

    queue_backend = PostgresQueueBackend(conn)
    notification_backend = LocalNotificationBackend()

    results_backend = PostgresBackend(conn)
    PostgresBackend.create_table(conn, results_table)
    results_cache = ResultsCache(results_backend, results_table)

    app.state.models_config = _load_models_config()
    app.state.queue_backend = queue_backend
    app.state.notification_backend = notification_backend
    app.state.results_cache = results_cache
    app.state.topic = os.getenv("LIFECYCLE_TOPIC", "lifecycle")

    logger.info(
        "local backends configured: %d models, table='%s'",
        len(app.state.models_config),
        results_table,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    if _is_lambda():
        logger.info("Lambda environment detected -- skipping backend construction")
        app.state.models_config = {}
        app.state.queue_backend = None
        app.state.notification_backend = None
        app.state.results_cache = None
        app.state.topic = None
    elif os.getenv("DATABASE_URL"):
        _build_local_backends(app)
    else:
        logger.warning(
            "neither Lambda environment nor DATABASE_URL detected -- "
            "route handlers will fail if called"
        )
        app.state.models_config = {}
        app.state.queue_backend = None
        app.state.notification_backend = None
        app.state.results_cache = None
        app.state.topic = None

    yield


app = FastAPI(
    title="Marigold",
    description="Hosted model inference API.",
    version=os.getenv("BUILD_VERSION", "dev"),
    lifespan=lifespan,
)

app.include_router(router)


@app.exception_handler(Exception)
async def unhandled_exception(request, exc):
    logger.exception("unhandled exception: %s", exc)
    return JSONResponse(status_code=500, content={"status": "error", "message": "internal error"})
