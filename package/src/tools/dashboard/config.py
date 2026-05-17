"""
Dashboard configuration.

Single source for env vars, AWS client singletons, and constants.
All other modules import from here. No direct os.environ access elsewhere.
"""
import os
import boto3

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

API_BASE = os.environ.get("MARIGOLD_API_BASE", "https://api.dev.mdl.bayis.co.uk")
API_KEY  = os.environ.get("MARIGOLD_API_KEY",  "")
REGION   = os.environ.get("AWS_REGION",        "eu-west-2")

# ECS cluster name or ARN
CLUSTER  = os.environ.get("MARIGOLD_ECS_CLUSTER", "bayis-vecmdl-dev-inference")

# Project tag value used to filter ASGs
PROJECT  = os.environ.get("MARIGOLD_PROJECT", "vecmdl")

# Resource name prefix (org-project-env)
PREFIX   = os.environ.get("MARIGOLD_PREFIX",  "bayis-vecmdl-dev")

# Org name
ORG      = os.environ.get("MARIGOLD_ORG",     "bayis")

# CloudWatch log group prefix for error scanning
LOG_GROUP_PREFIX = os.environ.get(
    "MARIGOLD_LOG_GROUP_PREFIX",
    "/bayis/vecmdl/dev",
)

# DynamoDB tables to monitor (comma-separated)
_TABLES_RAW = os.environ.get("MARIGOLD_DYNAMODB_TABLES", "")
DYNAMODB_TABLES = (
    [t.strip() for t in _TABLES_RAW.split(",") if t.strip()]
    if _TABLES_RAW else [
        "bayis-vecmdl-dev-model-events",
        "bayis-vecmdl-dev-results-cache",
        "bayis-vecmdl-dev-usage",
        "bayis-vecmdl-dev-users",
        "bayis-vecmdl-dev-workflow-state",
        "bayis-vecmdl-dev-workflow-steps",
        "bayis-vecmdl-dev-workflow-tasks",
        "bayis-vecmdl-dev-workflow-templates",
    ]
)

# ---------------------------------------------------------------------------
# AWS clients (singletons -- created once at import time)
# ---------------------------------------------------------------------------

_session = boto3.Session(region_name=REGION)

asg_client  = _session.client("autoscaling")
ec2_client  = _session.client("ec2")
ecs_client  = _session.client("ecs")
sqs_client  = _session.client("sqs")
cw_client   = _session.client("cloudwatch")
logs_client = _session.client("logs")
ddb_client  = _session.client("dynamodb")

# ---------------------------------------------------------------------------
# API headers
# ---------------------------------------------------------------------------

API_HEADERS = {
    "x-api-key":    API_KEY,
    "Content-Type": "application/json",
}
