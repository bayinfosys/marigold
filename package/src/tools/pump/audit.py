"""
Pump job audit.

Reads job history from MARIGOLD_PUMP_HISTORY, polls each job's result
endpoint, and updates the history record in place with the result.

Records are updated with:
    status, duration_ms, input_tokens, output_tokens, error (if any)

A record with status already set to "complete" or "error" is not re-polled.
"""
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

import requests

from tools.dashboard.config import API_BASE, API_HEADERS

log = logging.getLogger("pump.audit")


# ---------------------------------------------------------------------------
# Poll
# ---------------------------------------------------------------------------

def poll_result(poll_url: str) -> dict:
    """
    Poll a single job result. Returns a dict with at minimum a 'status' key.
    Does not block -- returns whatever the current status is.
    """
    url = "%s%s" % (API_BASE, poll_url)
    try:
        r = requests.get(url, headers=API_HEADERS, timeout=10)
        if r.status_code not in (200, 202):
            log.warning("[%03i] %s" % (r.status_code, r.text))
            return {"status": "fetch_error", "error": "http_%d" % r.status_code}
        return r.json()
    except requests.exceptions.RequestException as e:
        log.exception("[%03i] %s", r.status_code, r.text)
        return {"status": "fetch_error", "error": str(e)}


def extract_stats(response: dict) -> dict:
    """Extract usage stats and error from a poll response."""
    result = response.get("result") or {}
    usage  = result.get("usage") or {}
    error  = result.get("error")
    return {
        "status":        response.get("status", "unknown"),
        "duration_ms":   usage.get("duration",      0),
        "inference_ms":  usage.get("inference",      0),
        "input_tokens":  usage.get("input_tokens",   0),
        "output_tokens": usage.get("output_tokens",  0),
        "memory_kb":     usage.get("memory_usage",   0),
        "error":         error,
    }


# ---------------------------------------------------------------------------
# History file operations
# ---------------------------------------------------------------------------

def history_path(date_str: str) -> Path:
    raw = os.environ.get("MARIGOLD_PUMP_HISTORY", "~/.marigold")
    return Path(os.path.expanduser(raw)) / ("%s.jsonl" % date_str)


def read_history(date_str: str) -> List[dict]:
    path = history_path(date_str)
    if not path.exists():
        return []
    entries = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return entries


def write_history(date_str: str, entries: List[dict]) -> None:
    path = history_path(date_str)
    path.write_text(
        "\n".join(json.dumps(e) for e in entries) + "\n"
    )


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

def audit_date(date_str: str, force: bool = False) -> dict:
    """
    Audit all jobs in a history file for one date.

    Polls jobs that are not yet complete/error.
    Updates records in place and writes the file back.

    force=True re-polls all jobs regardless of current status.

    Returns summary counts.
    """
    entries = read_history(date_str)
    if not entries:
        log.info("no history for %s", date_str)
        return {"total": 0}

    log.info("auditing %d job(s) from %s", len(entries), date_str)

    counts = {
        "total":    len(entries),
        "complete": 0,
        "error":    0,
        "pending":  0,
        "skipped":  0,
    }

    updated = False
    for entry in entries:
        current_status = entry.get("status")

        # Skip already-resolved entries unless force is set
        if not force and current_status in ("complete", "error"):
            counts["skipped"] += 1
            continue

        poll_url = entry.get("poll_url")
        if not poll_url:
            log.warning("no poll_url for %s -- skipping", entry.get("message_id"))
            continue

        response = poll_result(poll_url)
        stats    = extract_stats(response)

        entry.update(stats)
        updated = True

        status = stats["status"]
        if status == "complete":
            counts["complete"] += 1
            log.info(
                "[%s/%s] complete  dur=%dms  inf=%dms  tok=%d+%d",
                entry.get("model_type", "?"),
                entry.get("model", "?")[:40],
                stats["duration_ms"],
                stats["inference_ms"],
                stats["input_tokens"],
                stats["output_tokens"],
            )
        elif status == "error":
            counts["error"] += 1
            log.info(
                "[%s/%s] error  %s",
                entry.get("model_type", "?"),
                entry.get("model", "?")[:40],
                stats.get("error", "")[:80],
            )
        else:
            counts["pending"] += 1
            log.info(
                "[%s/%s] %s",
                entry.get("model_type", "?"),
                entry.get("model", "?")[:40],
                status,
            )

    if updated:
        write_history(date_str, entries)
        log.info("updated history file %s", history_path(date_str))

    return counts


def print_report(date_str: str) -> None:
    entries = read_history(date_str)
    if not entries:
        print("no history for %s" % date_str)
        return

    complete = [e for e in entries if e.get("status") == "complete"]
    errors   = [e for e in entries if e.get("status") == "error"]
    pending  = [e for e in entries if e.get("status") not in ("complete", "error")]

    print()
    print("Pump audit  %s  (%d jobs)" % (date_str, len(entries)))
    print()

    # Per-model-type breakdown
    by_type = {}
    for e in complete:
        t = e.get("model_type", "unknown")
        by_type.setdefault(t, []).append(e)

    if by_type:
        print("  %-20s %6s %8s %8s %8s %8s" % (
            "Type", "n", "p50_ms", "p95_ms", "min_ms", "max_ms"
        ))
        print("  " + "-" * 64)

        for model_type in sorted(by_type):
            durs = sorted(
                e["duration_ms"] for e in by_type[model_type]
                if e.get("duration_ms")
            )
            if not durs:
                continue
            n   = len(durs)
            p50 = durs[n // 2]
            p95 = durs[min(int(n * 0.95), n - 1)]
            print("  %-20s %6d %8d %8d %8d %8d" % (
                model_type[:20], n, p50, p95, durs[0], durs[-1]
            ))

        print()

    # Per-model breakdown
    by_model = {}
    for e in complete:
        k = (e.get("model_type", "?"), e.get("model", "?"))
        by_model.setdefault(k, []).append(e)

    if by_model:
        print("  %-45s %-16s %6s %8s %8s %8s" % (
            "Model", "Type", "n", "p50_ms", "p95_ms", "tok_out"
        ))
        print("  " + "-" * 100)

        for (model_type, model) in sorted(by_model):
            group = by_model[(model_type, model)]
            durs  = sorted(e["duration_ms"] for e in group if e.get("duration_ms"))
            if not durs:
                continue
            n      = len(durs)
            p50    = durs[n // 2]
            p95    = durs[min(int(n * 0.95), n - 1)]
            tok    = sum(e.get("output_tokens", 0) for e in group)
            print("  %-45s %-16s %6d %8d %8d %8d" % (
                model[:45], model_type[:16], n, p50, p95, tok
            ))

        print()

    # Summary
    print("  complete=%d  error=%d  pending=%d  total=%d" % (
        len(complete), len(errors), len(pending), len(entries)
    ))

    if complete:
        all_durs = sorted(e["duration_ms"] for e in complete if e.get("duration_ms"))
        if all_durs:
            n   = len(all_durs)
            p50 = all_durs[n // 2]
            p95 = all_durs[min(int(n * 0.95), n - 1)]
            tok = sum(e.get("input_tokens", 0) + e.get("output_tokens", 0)
                      for e in complete)
            print("  overall p50=%dms  p95=%dms  total_tokens=%d" % (
                p50, p95, tok
            ))
    print()

#
# cmd
#

def cmd_audit(args) -> None:
    """Poll results for previously submitted jobs and update history."""
    now = datetime.now(timezone.utc)

    # Build list of dates to audit
    if args.date:
        dates = [args.date]
    else:
        dates = [
            (now - timedelta(days=i)).strftime("%Y-%m-%d")
            for i in range(args.days)
        ]

    for date_str in dates:
        if args.poll:
            counts = audit_date(date_str, force=args.force)
            log.info(
                "%s: complete=%d  error=%d  pending=%d  skipped=%d",
                date_str,
                counts.get("complete", 0),
                counts.get("error",    0),
                counts.get("pending",  0),
                counts.get("skipped",  0),
            )

        if args.report:
            print_report(date_str)
