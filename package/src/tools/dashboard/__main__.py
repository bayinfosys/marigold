"""
Marigold dashboard entry point.

Collects data from the Marigold API and AWS, builds a DashboardData
snapshot, and renders it to the configured output format.

Usage:
    python3 -m tools.dashboard
    python3 -m tools.dashboard --once
    python3 -m tools.dashboard --interval 30
    python3 -m tools.dashboard --format json

Environment:
    MARIGOLD_API_BASE          API endpoint (default: https://api.dev.mdl.bayis.co.uk)
    MARIGOLD_API_KEY           API key
    MARIGOLD_ECS_CLUSTER       ECS cluster name
    MARIGOLD_PROJECT           Project tag value for ASG filter
    MARIGOLD_PREFIX            Resource name prefix
    MARIGOLD_ORG               Organisation prefix
    MARIGOLD_PUMP_HISTORY      Directory for pump history JSONL files
    MARIGOLD_DYNAMODB_TABLES   Comma-separated table names to monitor
    MARIGOLD_LOG_GROUP_PREFIX  CloudWatch log group prefix for error scan
    AWS_REGION                 AWS region (default: eu-west-2)
"""
import argparse
import json
import logging
import os
import time

from .config import (
    CLUSTER, PREFIX, ORG,
    DYNAMODB_TABLES, LOG_GROUP_PREFIX,
)
from .fetch_api import fetch_models_json
from .fetch_aws import (
    fetch_efs_filesystems,
    fetch_efs_metrics,
    fetch_asgs,
    fetch_ec2_instances,
    fetch_ecs_container_instances,
    fetch_running_tasks,
    fetch_ecs_services,
    fetch_all_queue_urls,
    fetch_sqs_queue_stats,
    fetch_dynamodb_write_metrics,
    fetch_recent_error_count,
)
from .transform import build_model_catalogue, build_dashboard, DashboardData
from .render.console import render as console_render

log = logging.getLogger("dashboard")
log.setLevel(os.getenv("LOG_LEVEL", "INFO"))


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------

def collect() -> DashboardData:
    """Fetch all data sources and build a DashboardData snapshot."""

    # API -- model catalogue (hash -> ModelInfo)
    raw_models = fetch_models_json()
    catalogue  = build_model_catalogue(raw_models)

    # AWS infrastructure
    raw_asgs   = fetch_asgs()
    all_ids    = [
        i["InstanceId"]
        for g in raw_asgs
        for i in g.get("Instances", [])
    ]
    ec2_map    = fetch_ec2_instances(all_ids)
    ecs_ci_map = fetch_ecs_container_instances()
    raw_tasks  = fetch_running_tasks()
    raw_svcs   = fetch_ecs_services()

    # SQS queues
    queue_urls  = fetch_all_queue_urls()
    queue_stats = fetch_sqs_queue_stats(queue_urls)

    # System health
    ddb_metrics = fetch_dynamodb_write_metrics(DYNAMODB_TABLES)
    error_count = fetch_recent_error_count(LOG_GROUP_PREFIX)

    efs_filesystems = fetch_efs_filesystems()
    fs_ids          = [f["FileSystemId"] for f in efs_filesystems]
    efs_metrics     = fetch_efs_metrics(fs_ids)

    return build_dashboard(
        raw_asgs         = raw_asgs,
        ec2_map          = ec2_map,
        ecs_ci_map       = ecs_ci_map,
        raw_tasks        = raw_tasks,
        raw_services     = raw_svcs,
        queue_stats      = queue_stats,
        catalogue        = catalogue,
        dynamodb_metrics = ddb_metrics,
        error_count      = error_count,
        prefix           = PREFIX,
        org              = ORG,
        efs_filesystems  = efs_filesystems,
        efs_metrics      = efs_metrics,
    )


# ---------------------------------------------------------------------------
# JSON renderer (stub for future use)
# ---------------------------------------------------------------------------

def json_render(data: DashboardData) -> None:
    print(json.dumps({
        "ts":      data.ts,
        "models":  {
            name: {
                "type":    ms.model_type,
                "running": ms.service.running,
                "desired": ms.service.desired,
                "pending": ms.service.pending,
                "queue":   ms.queue.visible,
                "placed":  ms.instance_id,
            }
            for name, ms in data.models.items()
        },
        "placed":  len(data.placed),
        "backlog": len(data.backlog),
        "unused":  len(data.unused),
        "errors":  data.error_count,
    }, indent=2))


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main(fmt: str) -> None:
    renderers = {
        "console": console_render,
        "json":    json_render,
    }
    renderer = renderers.get(fmt, console_render)

    start = time.time()
    try:
        data = collect()
        renderer(data)
    except KeyboardInterrupt:
        log.info("exiting...")
    except Exception as e:
        log.error("collect failed: %s", e)


if __name__ == "__main__":
    p = argparse.ArgumentParser(
        description="Marigold infrastructure dashboard",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--format", choices=["console", "json"], default="console",
        help="output format (default: console)",
    )

    args = p.parse_args()
    main(args.format)
