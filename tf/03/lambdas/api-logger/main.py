"""
API Gateway access log processor.

Triggered by a CloudWatch Logs subscription filter on the API Gateway
access log group. Parses structured JSON access log entries and writes
raw usage metrics to the usage DynamoDB table.

Each authenticated request produces one METRIC#RAW row. Unauthenticated
requests (health checks, OPTIONS, missing API key) are silently skipped.

The DynamoDB stream on the usage table triggers the usage-stats lambda
which aggregates these raw rows into daily and monthly METRIC#SUM rows.
"""
import base64
import gzip
import json
import logging
import os
from datetime import datetime

from dynawrap import DBItem, DynamodbWrapper

logger = logging.getLogger()
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))

USAGE_TABLE_NAME = os.environ["DYNAMODB_USAGE_TABLE"]


class RawUsageMetrics(DBItem):
    """Raw per-request metric row."""
    table_name  = USAGE_TABLE_NAME
    pk_pattern  = "METRIC#RAW#USER#{user_id}"
    sk_pattern  = "DATE#{date}#OP#{operation}"


db_wrapper = DynamodbWrapper(RawUsageMetrics)


def handler(event, context):
    compressed = base64.b64decode(event["awslogs"]["data"])
    payload    = json.loads(gzip.decompress(compressed))

    records = payload.get("logEvents", [])
    logger.info("processing %d log events", len(records))

    written = 0
    errors  = 0

    for record in records:
        try:
            written += process_log_event(record["message"])
        except Exception as e:
            logger.error("failed to process record: %s -- %s", record.get("message", ""), e)
            errors += 1

    logger.info("written=%d skipped=%d errors=%d", written, len(records) - written - errors, errors)


def process_log_event(message: str) -> int:
    """
    Parse one access log entry and write a raw metric row.
    Returns 1 if written, 0 if skipped.
    """
    try:
        data = json.loads(message)
    except json.JSONDecodeError:
        logger.debug("skipping non-JSON log entry")
        return 0

    api_key_id = data.get("apiKeyId", "")
    if not api_key_id or api_key_id == "-":
        # unauthenticated -- health checks, OPTIONS preflight, etc.
        return 0

    status        = int(data.get("status", 0))
    method        = data.get("method", "UNKNOWN")
    resource_path = data.get("resourcePath", "/")
    operation     = f"{method} {resource_path}"
    now           = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

    metrics = {
        "status":                  status,
        "response_bytes":          _int(data.get("responseBytes")),
        "response_latency_ms":     _int(data.get("responseLatencyMs")),
        "integration_latency_ms":  _int(data.get("integrationLatencyMs")),
        "source_ip":               data.get("sourceIp", ""),
        "request_id":              data.get("requestId", ""),
        "stage":                   data.get("stage", ""),
        "epoch_ms":                _int(data.get("epochMs")),
        # billing signals -- kept as numerics so the aggregator can sum them
        "is_error":                1 if status >= 400 else 0,
        "is_server_error":         1 if status >= 500 else 0,
        "is_rate_limited":         1 if status == 429 else 0,
        "error_message":           data.get("errorMessage", "") or "",
    }

    item = RawUsageMetrics(db_wrapper)
    item.save({
        "user_id":   api_key_id,
        "operation": operation,
        "date":      now,
        "data":      json.dumps(metrics),
    })

    logger.debug("wrote METRIC#RAW for %s %s -> %d", method, resource_path, status)
    return 1


def _int(value) -> int:
    """Safely convert a value to int, returning 0 on failure."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
