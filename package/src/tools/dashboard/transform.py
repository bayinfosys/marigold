"""
Data transformation and aggregation.

Takes raw dicts from fetch_aws.py / fetch_api.py and produces
typed domain dataclasses. No boto3 imports. No print statements.
No colour decisions -- those belong in the renderer.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Domain dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ModelInfo:
    """Model metadata from /models.json."""
    hash:     str
    name:     str
    type:     str
    provider: str = ""


@dataclass
class QueueStats:
    visible:   int           = 0
    in_flight: int           = 0
    delayed:   int           = 0
    dlq:       Optional[int] = None

    @property
    def total(self) -> int:
        return self.visible + self.in_flight + self.delayed


@dataclass
class ServiceStats:
    """ECS service counts for one model."""
    desired:  int           = 0
    running:  int           = 0
    pending:  int           = 0
    cpu_pct:  Optional[float] = None
    mem_pct:  Optional[float] = None


@dataclass
class InstanceInfo:
    """Physical and ECS state for one EC2 instance."""
    iid:          str
    itype:        str
    lifecycle:    str
    market:       str            # "spot" or "OD"
    uptime_m:     int
    # ECS resource state -- None means not registered yet
    cpu_rem:      Optional[int]   = None
    cpu_total:    Optional[int]   = None
    mem_used_g:   Optional[float] = None
    mem_total_g:  Optional[float] = None
    mem_pct:      Optional[float] = None
    cpu_pct:      Optional[float] = None
    gpu_rem:      Optional[int]   = None
    gpu_total:    Optional[int]   = None
    running:      Optional[int]   = None
    pending_ci:   Optional[int]   = None
    agent_ok:     Optional[bool]  = None
    ci_status:    Optional[str]   = None
    models:       List[str]       = field(default_factory=list)


@dataclass
class AsgInfo:
    name:        str
    short_name:  str
    desired:     int
    min_size:    int
    max_size:    int
    inservice:   int
    pending:     int
    terminating: int
    instances:   List[InstanceInfo] = field(default_factory=list)


@dataclass
class ModelStatus:
    """Combined view of one model: service state + queue depth + placement."""
    name:        str
    model_type:  str
    service:     ServiceStats
    queue:       QueueStats
    instance_id: Optional[str] = None    # set if a task is currently running


@dataclass
class DashboardData:
    """Complete point-in-time snapshot of dashboard state."""
    ts:               str
    asgs:             List[AsgInfo]
    models:           Dict[str, ModelStatus]   # model_name -> ModelStatus
    # partitioned views
    placed:           List[ModelStatus]        # running on an instance
    backlog:          List[ModelStatus]        # queue > 0, no running task
    unused:           List[ModelStatus]        # queue == 0, no running task
    # system health
    dynamodb_metrics: Dict[str, dict]          # table_name -> {writes, throttles}
    error_count:      int
    # efs
    efs_metrics: Dict[str, dict]   # fs_id -> {burst_credits_gb, ...}
    efs_names:   Dict[str, str]    # fs_id -> name tag or fs_id


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_resource(resources: list, name: str, key: str = "integerValue") -> int:
    for r in resources:
        if r["name"] == name:
            return r.get(key, 0)
    return 0


def _get_gpu_count(resources: list) -> int:
    for r in resources:
        if r["name"] == "GPU":
            return len(r.get("stringSetValue", []))
    return 0


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Model catalogue
# ---------------------------------------------------------------------------

def build_model_catalogue(raw: dict) -> Dict[str, ModelInfo]:
    """
    Build {hash: ModelInfo} from raw /models.json response.

    The /models.json response is keyed by model hash (md5 of lowercase
    model name). Each value contains at minimum name, type, provider.
    """
    result: Dict[str, ModelInfo] = {}
    for hash_key, m in raw.items():
        name = (m.get("name") or "").lower().strip()
        if not name:
            continue
        provider = m.get("provider", "")
        if isinstance(provider, dict):
            provider = provider.get("name", "")
        result[hash_key] = ModelInfo(
            hash     = hash_key,
            name     = name,
            type     = m.get("type", ""),
            provider = provider,
        )
    return result


def hash_to_name_map(catalogue: Dict[str, ModelInfo]) -> Dict[str, str]:
    """Return {hash: model_name} for task definition family name resolution."""
    return {h: m.name for h, m in catalogue.items()}


# ---------------------------------------------------------------------------
# Instance transform
# ---------------------------------------------------------------------------

def _build_instance_info(
    inst_ref:      dict,
    ec2_map:       Dict[str, dict],
    ecs_ci_map:    Dict[str, dict],
    tasks:         List[dict],
    ci_arn_to_ec2: Dict[str, str],
    h2n:           Dict[str, str],
) -> InstanceInfo:
    iid      = inst_ref["InstanceId"]
    inst     = ec2_map.get(iid, {})
    launch   = inst.get("LaunchTime")
    uptime_m = int((_now_utc() - launch).total_seconds() / 60) if launch else 0

    info = InstanceInfo(
        iid       = iid,
        itype     = inst.get("InstanceType", "?"),
        lifecycle = inst_ref["LifecycleState"],
        market    = "spot" if inst.get("InstanceLifecycle") == "spot" else "OD",
        uptime_m  = uptime_m,
    )

    ci = ecs_ci_map.get(iid)
    if ci:
        reg      = ci.get("registeredResources", [])
        rem      = ci.get("remainingResources",  [])
        cpu_tot  = _get_resource(reg, "CPU")
        mem_tot  = _get_resource(reg, "MEMORY")
        cpu_rem  = _get_resource(rem, "CPU")
        mem_rem  = _get_resource(rem, "MEMORY")
        mem_used = mem_tot - mem_rem

        info.cpu_rem     = cpu_rem
        info.cpu_total   = cpu_tot
        info.mem_used_g  = mem_used  / 1024
        info.mem_total_g = mem_tot   / 1024
        info.mem_pct     = 100.0 * mem_used / mem_tot  if mem_tot  else 0.0
        info.cpu_pct     = 100.0 * (1 - cpu_rem / cpu_tot) if cpu_tot else 0.0
        info.gpu_rem     = _get_gpu_count(rem)
        info.gpu_total   = _get_gpu_count(reg)
        info.running     = ci.get("runningTasksCount",  0)
        info.pending_ci  = ci.get("pendingTasksCount",  0)
        info.agent_ok    = ci.get("agentConnected",     False)
        info.ci_status   = ci.get("status",             "?")

        # Resolve which models are running on this instance
        ci_arn = ci.get("containerInstanceArn", "")
        for task in tasks:
            if task.get("containerInstanceArn") != ci_arn:
                continue
            # Task definition family: {prefix}-{model_hash}
            family   = task.get("taskDefinitionArn", "").split("/")[-1].split(":")[0]
            raw_hash = family.split("-")[-2]
            name     = h2n.get(raw_hash, raw_hash[:12] + "...")
            if name not in info.models:
                info.models.append(name)

    return info


# ---------------------------------------------------------------------------
# ASG transform
# ---------------------------------------------------------------------------

def build_asgs(
    raw_asgs:   List[dict],
    ec2_map:    Dict[str, dict],
    ecs_ci_map: Dict[str, dict],
    tasks:      List[dict],
    h2n:        Dict[str, str],
    prefix:     str,
    org:        str,
) -> List[AsgInfo]:
    # Container instance ARN -> EC2 ID for task resolution
    ci_arn_to_ec2 = {
        ci.get("containerInstanceArn", ""): ec2_id
        for ec2_id, ci in ecs_ci_map.items()
    }

    result = []
    for g in raw_asgs:
        name       = g["AutoScalingGroupName"]
        short_name = name.replace("%s-%s-" % (org, prefix), "").replace("%s-" % prefix, "")
        instances_raw = g.get("Instances", [])

        asg_info = AsgInfo(
            name        = name,
            short_name  = short_name,
            desired     = g["DesiredCapacity"],
            min_size    = g["MinSize"],
            max_size    = g["MaxSize"],
            inservice   = sum(1 for i in instances_raw if i["LifecycleState"] == "InService"),
            pending     = sum(1 for i in instances_raw if "Pending"     in i["LifecycleState"]),
            terminating = sum(1 for i in instances_raw if "Terminating" in i["LifecycleState"]),
        )

        for inst_ref in sorted(instances_raw, key=lambda x: x["InstanceId"]):
            asg_info.instances.append(
                _build_instance_info(
                    inst_ref, ec2_map, ecs_ci_map, tasks, ci_arn_to_ec2, h2n
                )
            )

        result.append(asg_info)

    return result


# ---------------------------------------------------------------------------
# Model status transform
# ---------------------------------------------------------------------------

def build_model_statuses(
    catalogue:    Dict[str, ModelInfo],
    raw_services: List[dict],
    queue_stats:  Dict[str, dict],
    asgs:         List[AsgInfo],
) -> Dict[str, ModelStatus]:
    """
    Build a ModelStatus for every model in the catalogue by joining:
      - ECS service desiredCount / runningCount / pendingCount
      - SQS queue depth (visible, in_flight, delayed)
      - Physical placement (which EC2 instance, if any)
    """

    # service name -> hash extracted from service name suffix
    # service name format: {prefix}-{hash} or {project}-{env}-{hash}
    name_to_svc: Dict[str, ServiceStats] = {}
    for svc in raw_services:
        svc_name = svc.get("serviceName", "")
        # Extract the last 32-char hex segment as the model hash
        m = re.search(r"([a-f0-9]{32})$", svc_name)
        if m:
            raw_hash = m.group(1)
            if raw_hash in catalogue:
                model_name = catalogue[raw_hash].name
                name_to_svc[model_name] = ServiceStats(
                    desired = svc.get("desiredCount", 0),
                    running = svc.get("runningCount",  0),
                    pending = svc.get("pendingCount",  0),
                )

    # Queue URL -> hash, queue URL format ends with {hash}-queue
    hash_to_qstats: Dict[str, dict] = {}
    for url, stats in queue_stats.items():
        m = re.search(r"-([a-f0-9]{32})-queue", url)
        if m:
            hash_to_qstats[m.group(1)] = stats

    # Instance placement: model_name -> ec2_instance_id
    model_to_instance: Dict[str, str] = {}
    for asg in asgs:
        for inst in asg.instances:
            for model_name in inst.models:
                model_to_instance[model_name] = inst.iid

    result: Dict[str, ModelStatus] = {}
    for hash_key, model in catalogue.items():
        qs_raw = hash_to_qstats.get(hash_key, {})
        qs     = QueueStats(
            visible   = qs_raw.get("visible",   0),
            in_flight = qs_raw.get("in_flight", 0),
            delayed   = qs_raw.get("delayed",   0),
        )
        svc = name_to_svc.get(model.name, ServiceStats())

        result[model.name] = ModelStatus(
            name        = model.name,
            model_type  = model.type,
            service     = svc,
            queue       = qs,
            instance_id = model_to_instance.get(model.name),
        )

    return result


# ---------------------------------------------------------------------------
# Partition
# ---------------------------------------------------------------------------

def partition_models(
    models: Dict[str, ModelStatus],
) -> Tuple[List[ModelStatus], List[ModelStatus], List[ModelStatus]]:
    """
    Split all models into three groups for display:
      placed   -- instance_id is set (task running)
      backlog  -- queue.total > 0, not placed (work waiting, no worker)
      unused   -- queue.total == 0, not placed (idle, nothing queued)
    """
    placed  = []
    backlog = []
    unused  = []

    for m in models.values():
        if m.instance_id:
            placed.append(m)
        elif m.queue.total > 0:
            backlog.append(m)
        else:
            unused.append(m)

    placed.sort(key=lambda x: (x.instance_id or "", x.name))
    backlog.sort(key=lambda x: x.queue.total, reverse=True)
    unused.sort(key=lambda x: x.name)

    return placed, backlog, unused


# ---------------------------------------------------------------------------
# Top-level builder
# ---------------------------------------------------------------------------

def build_dashboard(
    raw_asgs:         List[dict],
    ec2_map:          Dict[str, dict],
    ecs_ci_map:       Dict[str, dict],
    raw_tasks:        List[dict],
    raw_services:     List[dict],
    queue_stats:      Dict[str, dict],
    catalogue:        Dict[str, ModelInfo],
    dynamodb_metrics: Dict[str, dict],
    error_count:      int,
    prefix:           str,
    org:              str,
    efs_filesystems:  List[dict],
    efs_metrics:      Dict[str, dict],
) -> DashboardData:
    h2n    = hash_to_name_map(catalogue)
    asgs   = build_asgs(raw_asgs, ec2_map, ecs_ci_map, raw_tasks, h2n, prefix, org)
    models = build_model_statuses(catalogue, raw_services, queue_stats, asgs)
    placed, backlog, unused = partition_models(models)

    # derive friendly names from EFS tags
    efs_names = {
        f["FileSystemId"]: next(
            (t["Value"] for t in f.get("Tags", []) if t["Key"] == "Name"),
            f["FileSystemId"],
        )
        for f in efs_filesystems
    }

    return DashboardData(
        ts               = _now_utc().strftime("%Y-%m-%dT%H:%M:%SZ"),
        asgs             = asgs,
        models           = models,
        placed           = placed,
        backlog          = backlog,
        unused           = unused,
        dynamodb_metrics = dynamodb_metrics,
        error_count      = error_count,
        efs_metrics      = efs_metrics,
        efs_names        = efs_names,
    )
