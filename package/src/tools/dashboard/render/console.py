"""
Terminal console renderer.

Takes DashboardData and prints a human-readable dashboard to stdout.
All colour decisions live here -- transform.py has no colour knowledge.
"""
import os
import sys
from datetime import datetime, timezone
from typing import Dict

from ..transform import AsgInfo, DashboardData, InstanceInfo, ModelStatus


# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------

_USE_COLOUR = sys.stdout.isatty() or os.environ.get("FORCE_COLOR") == "1"


def _c(code: str, text: str) -> str:
    return "\033[%sm%s\033[0m" % (code, text) if _USE_COLOUR else text


def green(s):  return _c("32", s)
def yellow(s): return _c("33", s)
def red(s):    return _c("31", s)
def bold(s):   return _c("1",  s)
def dim(s):    return _c("2",  s)
def cyan(s):   return _c("36", s)


# ---------------------------------------------------------------------------
# Infrastructure section
# ---------------------------------------------------------------------------

def _fmt_uptime(minutes: int) -> str:
    if minutes < 60:
        return "%dm"  % minutes
    if minutes < 1440:
        return "%dh"  % (minutes // 60)
    return "%dd" % (minutes // 1440)


def _print_asg_header(a: AsgInfo) -> None:
    line = "  %s  (des=%d min=%d max=%d  in-service=%d pending=%d terminating=%d)" % (
        a.short_name,
        a.desired, a.min_size, a.max_size,
        a.inservice, a.pending, a.terminating,
    )
    if a.inservice > 0:
        print(green(line))
    elif a.desired > 0:
        print(yellow(line))
    else:
        print(dim(line))


def _print_instance_row(
    inst:   InstanceInfo,
    models: Dict[str, ModelStatus],
) -> None:
    uptime_s = _fmt_uptime(inst.uptime_m)

    if inst.cpu_rem is None:
        row = "    %-22s %-14s %-12s %5s %7s  |  %8s %14s %10s %8s" % (
            inst.iid, inst.itype, inst.lifecycle, inst.market, uptime_s,
            "--", "not registered", "--", "--",
        )
        print(yellow(row))
        return

    gpu_s   = "%d/%d" % (inst.gpu_rem, inst.gpu_total) if inst.gpu_total else "  -"
    tasks_s = "%d+%d" % (inst.running, inst.pending_ci)
    mem_s   = "%4.1fG/%4.1fG" % (inst.mem_used_g, inst.mem_total_g)
    agent_s = "" if inst.agent_ok else red(" [disconnected]")

    row = "    %-22s %-14s %-12s %5s %7s  |  %8d %14s %10s %8s%s" % (
        inst.iid, inst.itype, inst.lifecycle, inst.market, uptime_s,
        inst.cpu_rem, mem_s, gpu_s, tasks_s, agent_s,
    )

    if not inst.agent_ok or inst.ci_status != "ACTIVE":
        print(yellow(row))
    elif inst.mem_pct > 85 or inst.cpu_pct > 85:
        print(red(row))
    elif inst.mem_pct > 60 or inst.running > 0:
        print(green(row))
    else:
        print(row)

    # Models running on this instance -- one sub-row each
    for model_name in inst.models:
        ms = models.get(model_name)
        if ms:
            _print_model_row(ms, indent=6)
        else:
            print("      + %s" % model_name)


def _print_model_row(ms: ModelStatus, indent: int = 6) -> None:
    pad   = " " * indent
    svc   = ms.service
    q     = ms.queue
    dlq_s = str(q.dlq) if q.dlq is not None else "-"

    row = "%s+ %-45s  des=%-2d run=%-2d pnd=%-2d  |  q=%-4d fl=%-4d dlq=%s" % (
        pad, ms.name,
        svc.desired, svc.running, svc.pending,
        q.visible, q.in_flight, dlq_s,
    )

    if svc.running > 0 and q.total == 0:
        print(green(row))
    elif svc.running > 0 and q.total > 0:
        print(cyan(row))     # running but queue building up
    elif svc.pending > 0:
        print(yellow(row))
    else:
        print(row)


def section_infrastructure(data: DashboardData) -> None:
    print(bold("--- Infrastructure ---"))
    print("    %-22s %-14s %-12s %5s %7s  |  %8s %14s %10s %8s" % (
        "Instance", "Type", "State", "Mkt", "Uptime",
        "CPU rem", "Mem used/total", "GPU", "Tasks r+p",
    ))

    if not data.asgs:
        print("  no ASGs found")
        print()
        return

    for a in data.asgs:
        _print_asg_header(a)
        for inst in a.instances:
            _print_instance_row(inst, data.models)
        print()

    print()


# ---------------------------------------------------------------------------
# Backlog section
# ---------------------------------------------------------------------------

def section_backlog(data: DashboardData) -> None:
    if not data.backlog:
        return

    print(bold("--- Backlog (queued, no running task) ---"))
    print("  %-45s %-18s %8s %8s %6s" % (
        "Model", "Type", "Visible", "InFlight", "DLQ",
    ))
    print("  " + "-" * 92)

    for ms in data.backlog:
        q     = ms.queue
        dlq_s = str(q.dlq) if q.dlq is not None else "-"
        row   = "  %-45s %-18s %8d %8d %6s" % (
            ms.name, ms.model_type,
            q.visible, q.in_flight, dlq_s,
        )
        print(yellow(row))

    print()


# ---------------------------------------------------------------------------
# Unused section (compact)
# ---------------------------------------------------------------------------

def section_unused(data: DashboardData) -> None:
    if not data.unused:
        return

    print(bold("--- Unused (%d model(s), queue empty, no task) ---" % len(data.unused)))

    names = [m.name for m in data.unused]
    col_w = 46
    cols  = 3
    for i in range(0, len(names), cols):
        row_names = names[i:i+cols]
        row = "  " + "".join("%-*s" % (col_w, n) for n in row_names)
        print(dim(row.rstrip()))

    print()


# ---------------------------------------------------------------------------
# DynamoDB section
# ---------------------------------------------------------------------------

def section_dynamodb(data: DashboardData) -> None:
    if not data.dynamodb_metrics:
        return

    print(bold("--- DynamoDB (last 5m) ---"))
    print("  %-48s %8s %12s" % ("Table", "Writes", "Throttles"))

    for table, metrics in sorted(data.dynamodb_metrics.items()):
        writes    = metrics.get("writes",    0)
        throttles = metrics.get("throttles", 0)
        # Strip prefix from table name for display
        short = table.split("-")[-1] if "-" in table else table
        row   = "  %-48s %8d %12d" % (table, writes, throttles)
        if throttles > 0:
            print(red(row))
        elif writes > 0:
            print(green(row))
        else:
            print(row)

    print()

# ---------------------------------------------------------------------------
# EFS
# ---------------------------------------------------------------------------

def section_efs(data: DashboardData) -> None:
    if not data.efs_metrics:
        return

    print(bold("--- EFS (last 5m) ---"))
    print("  %-30s %12s %16s %12s %14s" % (
        "Filesystem", "Burst (GB)", "Throughput MB/s", "Read bytes", "Connections",
    ))

    for fs_id, m in sorted(data.efs_metrics.items()):
        name     = data.efs_names.get(fs_id, fs_id)
        burst    = m.get("burst_credits_gb")
        tput     = m.get("permitted_throughput_mbs")
        reads    = m.get("read_bytes")
        conns    = m.get("client_connections")

        burst_s  = "%.1f" % burst if burst is not None else "--"
        tput_s   = "%.1f" % tput  if tput  is not None else "--"
        reads_s  = "%d"   % reads if reads is not None else "--"
        conns_s  = "%d"   % conns if conns is not None else "--"

        row = "  %-30s %12s %16s %12s %14s" % (
            name[:30], burst_s, tput_s, reads_s, conns_s,
        )

        # Burst credits below 1GB is a warning -- throughput will be throttled
        if burst is not None and burst < 1.0:
            print(red(row))
        elif reads is not None and reads > 100 * 1024**2:
            print(yellow(row))   # significant read activity
        else:
            print(row)

    print()


# ---------------------------------------------------------------------------
# Errors section
# ---------------------------------------------------------------------------

def section_errors(data: DashboardData) -> None:
    print(bold("--- Recent Errors (last 5m) ---"))
    if data.error_count == 0:
        print(dim("  no errors"))
    else:
        print(red("  %d error(s) in last 5 minutes" % data.error_count))
    print()


# ---------------------------------------------------------------------------
# Summary line
# ---------------------------------------------------------------------------

def section_summary(data: DashboardData) -> None:
    total   = len(data.models)
    running = sum(1 for m in data.models.values() if m.service.running > 0)
    backlog = len(data.backlog)
    unused  = len(data.unused)
    active_q = sum(
        m.queue.total for m in data.models.values()
    )
    print(dim(
        "  models=%d  running=%d  backlog=%d  unused=%d  queue_total=%d"
        % (total, running, backlog, unused, active_q)
    ))
    print()


# ---------------------------------------------------------------------------
# Full render
# ---------------------------------------------------------------------------

def render(data: DashboardData) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print()
    print(bold("Marigold Dashboard  bayis-vecmdl-dev  %s" % ts))
    print()
    section_infrastructure(data)
    section_backlog(data)
    section_unused(data)
    #section_dynamodb(data)
    section_efs(data)
    section_errors(data)
    section_summary(data)
