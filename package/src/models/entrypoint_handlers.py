"""Entry point handlers for the Marigold worker.

Each function constructs the appropriate backend objects and starts the
worker loop. They are called directly by the container CMD and never
imported transitively.

Entry points
------------
sqs_handler()   -- AWS ECS production path. Single model, SQS/SNS backends,
                   models_config.json loaded from S3 or local file. Unchanged
                   by the catalogue migration below -- out of scope.
local_handler() -- Local development path. One or more models, Postgres
                   backends, model catalogue read from the models table
                   (populated separately by the API's startup hook).

models_config.json (sqs_handler only)
--------------------------------------
Keyed by md5(model_name). On AWS this file lives in S3.

Environment variables
---------------------
Both handlers:
    MARIGOLD_MODELS           comma-separated model hash(es); unset/empty
                              means "serve everything available"
    SQS_VISIBILITY_TIMEOUT    seconds (default: 300)
    LIFECYCLE_TOPIC           topic name / ARN (default: "lifecycle")
    IDLE_TIMEOUT              seconds before idle exit; -1 for indefinite

sqs_handler (additional):
    MODELS_CONFIG_S3_OBJECT   S3 key for models_config.json
    AWS_S3_ASSETS_BUCKET_NAME S3 bucket name
    AWS_ENDPOINT_URL          optional endpoint override (LocalStack)

local_handler (additional):
    MARIGOLD_DATABASE_URL              psycopg2 DSN
    MARIGOLD_MODEL_CATALOGUE_TABLE              model catalogue table name (default: models)
    MARIGOLD_RESULTS_TABLE             results table name (default: results)
"""

import json
import logging
import os
import sys

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared utilities -- sqs_handler only, unchanged
# ---------------------------------------------------------------------------


def _load_models_config() -> dict:
    """Load models_config.json from S3 or local filesystem. sqs_handler only."""
    s3_key = os.getenv("MODELS_CONFIG_S3_OBJECT")
    if s3_key:
        import boto3
        bucket = os.environ["AWS_S3_ASSETS_BUCKET_NAME"]
        endpoint_url = os.getenv("AWS_ENDPOINT_URL")
        s3 = boto3.client("s3", endpoint_url=endpoint_url)
        resp = s3.get_object(Bucket=bucket, Key=s3_key)
        return json.loads(resp["Body"].read())

    path = os.environ["MODELS_CONFIG_PATH"]
    with open(path) as f:
        return json.load(f)


def _resolve_model_hashes(config: dict) -> list[str]:
    """Parse MARIGOLD_MODELS against a models_config dict. sqs_handler only."""
    raw = os.environ.get("MARIGOLD_MODELS", "").strip()
    if not raw:
        logger.info("MARIGOLD_MODELS not set -- serving all %d models in config", len(config))
        return list(config.keys())
    hashes = [h.strip() for h in raw.split(",") if h.strip()]
    if not hashes:
        logger.error("MARIGOLD_MODELS is set but contains no valid entries")
        sys.exit(1)
    return hashes


def _resolve_model_entries(hashes: list[str], config: dict) -> list[dict]:
    """Look up each hash in models_config. sqs_handler only."""
    entries = []
    for h in hashes:
        if h not in config:
            logger.error(
                "model hash '%s' not found in models_config; available: %s",
                h, sorted(config.keys()),
            )
            sys.exit(1)
        entries.append({**config[h], "model_hash": h})
    return entries


# ---------------------------------------------------------------------------
# Local / Postgres catalogue resolution -- local_handler only
# ---------------------------------------------------------------------------


def _load_catalogue(conn, table: str) -> list:
    """Fetch the full active model catalogue from Postgres."""
    from dynawrap.backends.postgres import PostgresBackend
    from models.catalogue import get_all_models

    backend = PostgresBackend(conn)
    return get_all_models(backend, table)


# ---------------------------------------------------------------------------
# AWS / ECS entry point -- unchanged
# ---------------------------------------------------------------------------


def sqs_handler():
    """ECS task entry point for a single model. Unchanged -- out of scope."""
    from backend.messaging.sqs_sns import SNSNotificationBackend, SQSQueueBackend
    from models import load_all
    from models.worker import QueueWorker
    from shared.registry import _SPECS

    load_all()

    config = _load_models_config()
    hashes = _resolve_model_hashes(config)

    if len(hashes) != 1:
        logger.error(
            "sqs_handler expects exactly one model hash; got %d. "
            "Use local_handler for multi-model deployments.",
            len(hashes),
        )
        sys.exit(1)

    model_hash = hashes[0]
    entries = _resolve_model_entries([model_hash], config)
    entry = entries[0]

    model_name = entry.get("model_name") or entry.get("name")
    model_type = entry.get("model_type") or entry.get("type")
    queue_url = entry["queue_url"]
    visibility_timeout = int(os.getenv("SQS_VISIBILITY_TIMEOUT", "300"))
    topic = os.getenv("LIFECYCLE_TOPIC", "lifecycle")
    endpoint_url = os.getenv("AWS_ENDPOINT_URL")

    if model_type not in _SPECS:
        logger.error(
            "unknown model_type '%s' for model '%s'; registered types: %s",
            model_type, model_name, sorted(_SPECS),
        )
        sys.exit(0)

    queue_backend = SQSQueueBackend(endpoint_url=endpoint_url)
    queue_backend.add_queue_url(model_hash, queue_url)
    notification_backend = SNSNotificationBackend(endpoint_url=endpoint_url)

    worker = QueueWorker(
        queue=model_hash,
        model_name=model_name,
        model_type=model_type,
        model_hash=model_hash,
        queue_backend=queue_backend,
        notification_backend=notification_backend,
        visibility_timeout=visibility_timeout,
        topic=topic,
        results_cache=None,
    )
    worker.run()


# ---------------------------------------------------------------------------
# Local / Postgres entry point
# ---------------------------------------------------------------------------


def local_handler():
    """Local development entry point for one or more models.

    Constructs Postgres backends from DATABASE_URL. Reads the model
    catalogue from the models table -- populated separately by the API's
    startup hook, not by this handler. Creates queue tables and the
    results table if they do not exist (idempotent).

    Single entry     -> QueueWorker (idle_timeout=-1).
    Multiple entries -> MultiQueueWorker (idle_timeout=0, exits each queue
                        immediately so the next model can be loaded promptly).
    """
    import psycopg2
    from backend.messaging.local import LocalNotificationBackend
    from backend.messaging.postgres import PostgresQueueBackend
    from dynawrap.backends.postgres import PostgresBackend
    from models import load_all
    from models.worker import MultiQueueWorker, QueueWorker
    from tools.polling.results_cache import ResultsCache

    load_all()

    dsn = os.environ["MARIGOLD_DATABASE_URL"]
    visibility_timeout = int(os.getenv("SQS_VISIBILITY_TIMEOUT", "300"))
    topic = os.getenv("LIFECYCLE_TOPIC", "lifecycle")
    results_table = os.getenv("MARIGOLD_RESULTS_TABLE", "results")
    models_table = os.getenv("MARIGOLD_MODEL_CATALOGUE_TABLE", "models")

    conn = psycopg2.connect(dsn)
    conn.autocommit = True

    catalogue = _load_catalogue(conn, models_table)
    #logger.info("catalogue: %s", str(catalogue))
    for idx, model in enumerate(catalogue):
        logger.info("[%03i] %s", idx, str(model))
    logger.info("serving: %s", [m.name for m in catalogue])

    queue_backend = PostgresQueueBackend(conn)
    notification_backend = LocalNotificationBackend()

    results_backend = PostgresBackend(conn)
    PostgresBackend.create_table(conn, results_table)
    results_cache = ResultsCache(results_backend, results_table)

    for model in catalogue:
        queue_backend.create_queue(model.queue_name)

    if len(catalogue) == 1:
        entry = catalogue[0]
        worker = QueueWorker(
            queue=entry.queue_name,
            model_name=entry.name,
            model_type=entry.type,
            model_hash=entry.hash,
            queue_backend=queue_backend,
            notification_backend=notification_backend,
            visibility_timeout=visibility_timeout,
            topic=topic,
            idle_timeout=-1,
            results_cache=results_cache,
        )
    else:
        worker = MultiQueueWorker(
            model_catalogue=catalogue,  # requires the worker.py refactor flagged above
            queue_backend=queue_backend,
            notification_backend=notification_backend,
            visibility_timeout=visibility_timeout,
            topic=topic,
            idle_timeout=int(os.getenv("MARIGOLD_QUEUE_IDLE_TIMEOUT", "0")),
            results_cache=results_cache,
        )

    worker.run()
