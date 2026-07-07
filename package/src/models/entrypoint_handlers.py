"""Entry point handlers for the Marigold worker.

Each function constructs the appropriate backend objects and starts the
worker loop. They are called directly by the container CMD and never
imported transitively.

Entry points
------------
sqs_handler()   -- AWS ECS production path. Single model, SQS/SNS backends.
local_handler() -- Local development path. One or more models, Postgres backends.

models_config.json
------------------
Keyed by md5(model_name). Each entry contains at minimum:
    name        str   HuggingFace model identifier
    type        str   ModelType enum value
    queue_url   str   SQS queue URL (AWS only, not used locally)

On AWS this file lives in S3. Locally it is generated from models.yaml via:
    python3 scripts/generate_models_tfvars.py assets/models.yaml infra-data

Environment variables
---------------------
Both handlers:
    MARIGOLD_MODELS           comma-separated model hash(es)
    SQS_VISIBILITY_TIMEOUT    seconds (default: 300)
    LIFECYCLE_TOPIC           topic name / ARN (default: "lifecycle")
    IDLE_TIMEOUT              seconds before idle exit; -1 for indefinite
                              (default: 180; use -1 for local development)

sqs_handler (additional):
    MODELS_CONFIG_S3_OBJECT   S3 key for models_config.json
    AWS_S3_ASSETS_BUCKET_NAME S3 bucket name
    AWS_ENDPOINT_URL          optional endpoint override (LocalStack)

local_handler (additional):
    MODELS_CONFIG_PATH        local filesystem path to models_config.json
    DATABASE_URL              psycopg2 DSN
    RESULTS_TABLE             results table name (default: results)
"""

import json
import logging
import os
import sys

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------


def _queue_name(model_hash: str) -> str:
    """Derive a Postgres queue table name from a model hash.

    Uses underscores rather than hyphens because Postgres table identifiers
    cannot contain hyphens unquoted.

        mdl_{hash}_queue
    """
    return f"mdl_{model_hash}_queue"


def _load_models_config() -> dict:
    """Load models_config.json from S3 or local filesystem.

    Resolution order:
    1. If MODELS_CONFIG_S3_OBJECT is set, load from S3.
    2. Otherwise load from MODELS_CONFIG_PATH as a local file.
    """
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
    """Parse MARIGOLD_MODELS into a list of model hashes.

    If MARIGOLD_MODELS is unset or empty, all hashes in config are used.
    """
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
    """Look up each hash in models_config and return the resolved entries."""
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
# AWS / ECS entry point
# ---------------------------------------------------------------------------


def sqs_handler():
    """ECS task entry point for a single model.

    Constructs SQS and SNS backends, loads the model, and runs QueueWorker
    until the queue is idle. results_cache is None -- the AWS path writes
    results via outputs.update_results_table() inside _write_result().
    """
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
    config = _load_models_config()
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
        results_cache=None,  # AWS path: _write_result uses outputs.update_results_table
    )
    worker.run()


# ---------------------------------------------------------------------------
# Local / Postgres entry point
# ---------------------------------------------------------------------------


def local_handler():
    """Local development entry point for one or more models.

    Constructs Postgres backends from DATABASE_URL. Creates queue tables
    and the results table if they do not exist (idempotent).

    Single hash in MARIGOLD_MODELS -> QueueWorker (idle_timeout=-1).
    Multiple hashes                -> MultiQueueWorker (idle_timeout=0,
                                      exits each queue immediately so the
                                      next model can be loaded promptly).
    """
    import psycopg2
    from backend.messaging.local import LocalNotificationBackend
    from backend.messaging.postgres import PostgresQueueBackend
    from dynawrap.backends.postgres import PostgresBackend
    from models import load_all
    from models.worker import MultiQueueWorker, QueueWorker
    from tools.polling.results_cache import ResultsCache

    load_all()

    config = _load_models_config()
    hashes = _resolve_model_hashes(config)
    entries = _resolve_model_entries(hashes, config)

    dsn = os.environ["DATABASE_URL"]
    visibility_timeout = int(os.getenv("SQS_VISIBILITY_TIMEOUT", "300"))
    topic = os.getenv("LIFECYCLE_TOPIC", "lifecycle")
    results_table = os.getenv("RESULTS_TABLE", "results")

    logger.info(entries)

    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    queue_backend = PostgresQueueBackend(conn)
    notification_backend = LocalNotificationBackend()

    results_backend = PostgresBackend(conn)
    PostgresBackend.create_table(conn, results_table)
    results_cache = ResultsCache(results_backend, results_table)

    # Derive queue names and ensure tables exist.
    for entry in entries:
        entry["queue_name"] = _queue_name(entry["model_hash"])
        queue_backend.create_queue(entry["queue_name"])

    if len(entries) == 1:
        entry = entries[0]
        worker = QueueWorker(
            queue=entry["queue_name"],
            model_name=entry.get("model_name") or entry.get("name"),
            model_type=entry.get("model_type") or entry.get("type"),
            model_hash=entry["model_hash"],
            queue_backend=queue_backend,
            notification_backend=notification_backend,
            visibility_timeout=visibility_timeout,
            topic=topic,
            idle_timeout=-1,  # poll indefinitely in local dev
            results_cache=results_cache,
        )
    else:
        worker = MultiQueueWorker(
            entries=entries,
            queue_backend=queue_backend,
            notification_backend=notification_backend,
            visibility_timeout=visibility_timeout,
            topic=topic,
            idle_timeout=int(os.getenv("MARIGOLD_QUEUE_IDLE_TIMEOUT", "0")),  # if zero, exit each queue immediately to load next model
            results_cache=results_cache,
        )

    worker.run()
