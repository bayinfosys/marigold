"""
AWS boto3 data fetching.

All functions return raw AWS response dicts/lists.
No transform logic. No API calls. No print statements.

Functions return empty collections on failure so the dashboard
degrades gracefully when a service is unavailable or permissions
are missing.
"""
import os
import logging
import time
from typing import Dict, List, Optional

from .config import (
    CLUSTER, PROJECT, PREFIX,
    asg_client, ec2_client, ecs_client,
    sqs_client, cw_client, logs_client,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# EFS
# ---------------------------------------------------------------------------

def fetch_efs_filesystems() -> List[dict]:
    """Enumerate all EFS filesystems in the account/region."""
    import boto3
    REGION = os.getenv("AWS_REGION", "eu-west-2")
    efs = boto3.client("efs", region_name=REGION)
    try:
        r = efs.describe_file_systems()
        return r.get("FileSystems", [])
    except Exception as e:
        log.warning("fetch_efs_filesystems: %s", e)
        return []


def fetch_efs_metrics(fs_ids: List[str], period_minutes: int = 5) -> Dict[str, dict]:
    """
    Fetch CloudWatch metrics for a list of EFS filesystem IDs.
    Returns {fs_id: {burst_credits_gb, permitted_throughput_mbs,
                     read_bytes, client_connections}}.
    """
    end   = int(time.time())
    start = end - period_minutes * 60
    result = {}

    for fs_id in fs_ids:
        stats = {}
        for metric, key, divisor in [
            ("BurstCreditBalance",  "burst_credits_gb",        1024**3),
            ("PermittedThroughput", "permitted_throughput_mbs", 1024**2),
            ("DataReadIOBytes",     "read_bytes",               1),
            ("ClientConnections",   "client_connections",       1),
        ]:
            try:
                r = cw_client.get_metric_statistics(
                    Namespace  = "AWS/EFS",
                    MetricName = metric,
                    Dimensions = [{"Name": "FileSystemId", "Value": fs_id}],
                    StartTime  = start,
                    EndTime    = end,
                    Period     = period_minutes * 60,
                    Statistics = ["Average"] if metric != "DataReadIOBytes" else ["Sum"],
                )
                pts = r.get("Datapoints", [])
                if pts:
                    val = pts[-1].get("Average") or pts[-1].get("Sum") or 0
                    stats[key] = round(val / divisor, 2)
                else:
                    stats[key] = None
            except Exception as e:
                log.debug("fetch_efs_metrics %s/%s: %s", fs_id, metric, e)
                stats[key] = None
        result[fs_id] = stats

    return result


# ---------------------------------------------------------------------------
# ASG
# ---------------------------------------------------------------------------

def fetch_asgs() -> List[dict]:
    """
    Fetch all ASGs associated with this deployment.

    Tries project tag filter first; falls back to prefix match on name
    if the tag filter returns nothing (handles deployments without tags).
    """
    try:
        resp   = asg_client.describe_auto_scaling_groups(
            Filters=[{"Name": "tag:project", "Values": [PROJECT]}]
        )
        groups = resp.get("AutoScalingGroups", [])

        if not groups:
            resp   = asg_client.describe_auto_scaling_groups()
            groups = [
                g for g in resp.get("AutoScalingGroups", [])
                if PREFIX in g["AutoScalingGroupName"]
            ]

        return sorted(groups, key=lambda x: x["AutoScalingGroupName"])

    except Exception as e:
        log.warning("fetch_asgs: %s", e)
        return []


# ---------------------------------------------------------------------------
# EC2
# ---------------------------------------------------------------------------

def fetch_ec2_instances(instance_ids: List[str]) -> Dict[str, dict]:
    """
    Fetch EC2 instance details for a list of instance IDs.
    Returns {instance_id: instance_dict}.
    """
    if not instance_ids:
        return {}
    try:
        result = {}
        r      = ec2_client.describe_instances(InstanceIds=instance_ids)
        for res in r.get("Reservations", []):
            for inst in res.get("Instances", []):
                result[inst["InstanceId"]] = inst
        return result
    except Exception as e:
        log.warning("fetch_ec2_instances: %s", e)
        return {}


# ---------------------------------------------------------------------------
# ECS container instances
# ---------------------------------------------------------------------------

def fetch_ecs_container_instances() -> Dict[str, dict]:
    """
    Fetch all ECS container instances registered to the cluster.
    Returns {ec2_instance_id: container_instance_dict}.
    """
    result = {}
    try:
        ci_arns = []
        paginator = ecs_client.get_paginator("list_container_instances")
        for page in paginator.paginate(cluster=CLUSTER):
            ci_arns.extend(page.get("containerInstanceArns", []))

        for i in range(0, len(ci_arns), 100):
            r = ecs_client.describe_container_instances(
                cluster=CLUSTER,
                containerInstances=ci_arns[i:i+100],
            )
            for ci in r.get("containerInstances", []):
                ec2_id = ci.get("ec2InstanceId", "")
                if ec2_id:
                    result[ec2_id] = ci

    except Exception as e:
        log.warning("fetch_ecs_container_instances: %s", e)

    return result


# ---------------------------------------------------------------------------
# ECS tasks
# ---------------------------------------------------------------------------

def fetch_running_tasks() -> List[dict]:
    """
    Fetch all currently running tasks in the cluster with full detail.
    Returns list of task dicts including containerInstanceArn and
    taskDefinitionArn for model resolution.
    """
    try:
        task_arns = []
        paginator = ecs_client.get_paginator("list_tasks")
        for page in paginator.paginate(cluster=CLUSTER, desiredStatus="RUNNING"):
            task_arns.extend(page.get("taskArns", []))

        if not task_arns:
            return []

        tasks = []
        for i in range(0, len(task_arns), 100):
            r = ecs_client.describe_tasks(cluster=CLUSTER, tasks=task_arns[i:i+100])
            tasks.extend(r.get("tasks", []))
        return tasks

    except Exception as e:
        log.warning("fetch_running_tasks: %s", e)
        return []


# ---------------------------------------------------------------------------
# ECS services
# ---------------------------------------------------------------------------

def fetch_ecs_services() -> List[dict]:
    """
    Fetch all ECS services in the cluster with full detail.
    Returns list of service dicts including desiredCount, runningCount,
    pendingCount, and serviceName.
    """
    try:
        service_arns = []
        paginator    = ecs_client.get_paginator("list_services")
        for page in paginator.paginate(cluster=CLUSTER):
            service_arns.extend(page.get("serviceArns", []))

        if not service_arns:
            return []

        services = []
        # describe_services accepts max 10 per call
        for i in range(0, len(service_arns), 10):
            r = ecs_client.describe_services(
                cluster=CLUSTER,
                services=service_arns[i:i+10],
            )
            services.extend(r.get("services", []))
        return services

    except Exception as e:
        log.warning("fetch_ecs_services: %s", e)
        return []


# ---------------------------------------------------------------------------
# SQS
# ---------------------------------------------------------------------------

_SQS_ATTRS = [
    "ApproximateNumberOfMessages",
    "ApproximateNumberOfMessagesNotVisible",
    "ApproximateNumberOfMessagesDelayed",
]


def fetch_queue_stats(queue_urls: List[str]) -> Dict[str, dict]:
    """
    Fetch stats for a list of queue URLs.
    Returns {queue_url: {visible, in_flight, delayed, oldest_msg_s}}.
    """
    result = {}
    for url in queue_urls:
        try:
            r = sqs_client.get_queue_attributes(QueueUrl=url, AttributeNames=_SQS_ATTRS)
            a = r.get("Attributes", {})
            result[url] = {
                "visible":      int(a.get("ApproximateNumberOfMessages",          0)),
                "in_flight":    int(a.get("ApproximateNumberOfMessagesNotVisible", 0)),
                "delayed":      int(a.get("ApproximateNumberOfMessagesDelayed",    0)),
                "oldest_msg_s": 0,  # populated separately via fetch_queue_age_metrics
            }
        except Exception as e:
            log.warning("fetch_queue_stats %s: %s", url, e)
            result[url] = {"visible": 0, "in_flight": 0, "delayed": 0, "oldest_msg_s": 0}
    return result


def fetch_queue_age_metrics(queue_names: List[str]) -> Dict[str, int]:
    """
    Fetch ApproximateAgeOfOldestMessage from CloudWatch for a list of
    queue names (not URLs). Returns {queue_name: age_seconds}.
    Uses a single GetMetricData call for all queues.
    """
    if not queue_names:
        return {}

    import time
    end   = int(time.time())
    start = end - 120  # last 2 minutes -- 1 minute resolution on this metric

    queries = [
        {
            "Id":         "age_%d" % i,
            "MetricStat": {
                "Metric": {
                    "Namespace":  "AWS/SQS",
                    "MetricName": "ApproximateAgeOfOldestMessage",
                    "Dimensions": [{"Name": "QueueName", "Value": name}],
                },
                "Period": 60,
                "Stat":   "Maximum",
            },
            "ReturnData": True,
        }
        for i, name in enumerate(queue_names)
    ]

    result = {}
    try:
        r = cw_client.get_metric_data(
            MetricDataQueries = queries,
            StartTime         = start,
            EndTime           = end,
        )
        for i, name in enumerate(queue_names):
            values = r.get("MetricDataResults", [])[i].get("Values", [])
            result[name] = int(max(values)) if values else 0
    except Exception as e:
        log.warning("fetch_queue_age_metrics: %s", e)

    return result


def fetch_model_queue_urls() -> List[str]:
    """
    List all model work queues for this deployment.
    These are the per-model SQS queues that hold inference jobs.
    Excludes DLQs, the anonchat queue, and system queues.
    """
    try:
        r = sqs_client.list_queues(QueueNamePrefix=PREFIX)
        return [
            url for url in r.get("QueueUrls", [])
            if "-queue"         in url
            and "-dlq"          not in url
            and "-anonchat"     not in url
            and "-launch-queue" not in url
        ]
    except Exception as e:
        log.warning("fetch_model_queue_urls: %s", e)
        return []


def fetch_system_queue_urls() -> List[str]:
    names = [
        "%s-launch-queue.fifo" % PREFIX,
        "%s-launch-dlq.fifo"   % PREFIX,
        "%s-task-queuer-events" % PREFIX,
        "%s-task-queuer-events-dlq" % PREFIX,
    ]
    urls = []
    for name in names:
        try:
            url = sqs_client.get_queue_url(QueueName=name)["QueueUrl"]
            urls.append(url)
        except Exception as e:
            log.debug("fetch_system_queue_urls %s: %s", name, e)
    return urls


def fetch_all_queue_stats() -> Dict[str, Dict[str, dict]]:
    model_urls  = fetch_model_queue_urls()
    system_urls = fetch_system_queue_urls()

    model_stats  = fetch_queue_stats(model_urls)
    system_stats = fetch_queue_stats(system_urls)

    # Patch in CloudWatch age metrics for model queues
    # Queue name is the last path segment of the URL
    model_names = [url.split("/")[-1] for url in model_urls]
    age_map     = fetch_queue_age_metrics(model_names)
    for url in model_urls:
        name = url.split("/")[-1]
        if name in age_map:
            model_stats[url]["oldest_msg_s"] = age_map[name]

    return {
        "model":  model_stats,
        "system": system_stats,
    }


def fetch_dlq_depth(dlq_url: str) -> Optional[int]:
    """Fetch the message count of a DLQ. Returns None on failure."""
    try:
        r = sqs_client.get_queue_attributes(
            QueueUrl=dlq_url,
            AttributeNames=["ApproximateNumberOfMessages"],
        )
        return int(r["Attributes"].get("ApproximateNumberOfMessages", 0))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# DynamoDB metrics
# ---------------------------------------------------------------------------

def fetch_dynamodb_write_metrics(
    table_names:    List[str],
    period_minutes: int = 5,
) -> Dict[str, dict]:
    """
    Fetch recent write counts and throttle events for DynamoDB tables.
    Returns {table_name: {writes, throttles}}.
    """
    end   = int(time.time())
    start = end - period_minutes * 60
    result: Dict[str, dict] = {}

    for table in table_names:
        writes    = 0
        throttles = 0
        for metric, target in [
            ("ConsumedWriteCapacityUnits", "writes"),
            ("WriteThrottleEvents",        "throttles"),
        ]:
            try:
                r = cw_client.get_metric_statistics(
                    Namespace="AWS/DynamoDB",
                    MetricName=metric,
                    Dimensions=[{"Name": "TableName", "Value": table}],
                    StartTime=start,
                    EndTime=end,
                    Period=period_minutes * 60,
                    Statistics=["Sum"],
                )
                total = sum(p.get("Sum", 0) for p in r.get("Datapoints", []))
                if target == "writes":
                    writes = int(total)
                else:
                    throttles = int(total)
            except Exception as e:
                log.debug("fetch_dynamodb_write_metrics %s/%s: %s", table, metric, e)

        result[table] = {"writes": writes, "throttles": throttles}

    return result


# ---------------------------------------------------------------------------
# CloudWatch errors
# ---------------------------------------------------------------------------

def fetch_recent_error_count(
    log_group_prefix: str,
    minutes:          int = 5,
) -> int:
    """
    Count ERROR-level log entries across all log groups under prefix
    in the last N minutes. Capped at 20 groups to avoid API spam.
    """
    end_ms   = int(time.time() * 1000)
    start_ms = end_ms - minutes * 60 * 1000

    try:
        r      = logs_client.describe_log_groups(logGroupNamePrefix=log_group_prefix)
        groups = [g["logGroupName"] for g in r.get("logGroups", [])][:20]
    except Exception as e:
        log.debug("fetch_recent_error_count describe_log_groups: %s", e)
        return 0

    count = 0
    for group in groups:
        try:
            r2 = logs_client.filter_log_events(
                logGroupName=group,
                startTime=start_ms,
                endTime=end_ms,
                filterPattern="ERROR",
                limit=20,
            )
            count += len(r2.get("events", []))
        except Exception:
            pass

    return count
