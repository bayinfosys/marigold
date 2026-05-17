"""
Pump job history.

Records every submitted job to a JSONL file in MARIGOLD_PUMP_HISTORY dir.
One file per calendar day: {YYYY-MM-DD}.jsonl, append-only.

Used by:
  - tools/pump.py  (writes on submission)
  - tools/dashboard (reads for pump stats -- future)

The history record captures everything needed to poll the result later,
including the poll_url, so no knowledge of mode/task routing is needed
at query time.
"""
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Tuple

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Mode / task / poll URL routing
#
# Inferred from model type -- matches the ROUTE_MAP in the pump.
# ---------------------------------------------------------------------------

_ROUTES = {
    "instruct":        ("gen",   "instruct",       "/output/gen/instruct/{id}"),
    "text-embedding":  ("embed", "text",            "/output/embed/text/{id}"),
    "image-embedding": ("embed", "image",           "/output/embed/image/{id}"),
    "tts":             ("gen",   "tts",             "/output/gen/tts/{id}"),
    "txt2audio":       ("gen",   "txt2audio",       "/output/gen/txt2audio/{id}"),
    "txt2img":         ("gen",   "txt2img",         "/output/gen/txt2img/{id}"),
    "img2txt":         ("gen",   "img2txt",         "/output/gen/img2txt/{id}"),
    "depth":           ("gen",   "depth",           "/output/gen/depth/{id}"),
    "img2mask":        ("gen",   "img2mask",        "/output/gen/img2mask/{id}"),
    "text-eval":       ("eval",  "text",            "/output/eval/text/{id}"),
    "text-similarity": ("eval",  "text-similarity", "/output/eval/text-similarity/{id}"),
    "image-eval":      ("eval",  "image",           "/output/eval/image/{id}"),
    "image-text-eval": ("eval",  "image-text",      "/output/eval/image-text/{id}"),
}


def mode_and_task(model_type: str) -> Tuple[str, str]:
    route = _ROUTES.get(model_type)
    return (route[0], route[1]) if route else ("gen", model_type)


def poll_url_for(model_type: str, message_id: str) -> str:
    route = _ROUTES.get(model_type)
    if route:
        return route[2].format(id=message_id)
    return "/output/gen/%s/%s" % (model_type, message_id)


# ---------------------------------------------------------------------------
# Directory
# ---------------------------------------------------------------------------

def _history_dir() -> Optional[Path]:
    raw = os.environ.get("MARIGOLD_PUMP_HISTORY", "~/.marigold")
    d   = Path(os.path.expanduser(raw))
    try:
        d.mkdir(parents=True, exist_ok=True)
        return d
    except Exception as e:
        log.warning("cannot create history dir %s: %s", d, e)
        return None


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def write_entry(
    message_id:  str,
    model_name:  str,
    model_type:  str,
    nonce:       Optional[str] = None,
    pump_id:     str = ""
) -> None:
    """
    Append one job submission record to today's history file.

    Safe to call from a ThreadPoolExecutor -- file append is atomic
    for lines under 4KB on Linux/macOS (POSIX write guarantee).
    """
    d = _history_dir()
    if not d:
        return

    mode, task = mode_and_task(model_type)
    ts         = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    entry = {
        "message_id":   message_id,
        "model":        model_name,
        "model_type":   model_type,
        "mode":         mode,
        "task":         task,
        "submitted_at": ts,
        "nonce":        nonce,
        "poll_url":     poll_url_for(model_type, message_id),
        "pump_id":      pump_id
    }

    path = d / ("%s.jsonl" % ts[:10])
    try:
        with path.open("a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        log.warning("history.write_entry failed: %s", e)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def read_entries(days: int = 1) -> List[dict]:
    """
    Read history entries from the last N calendar days.
    Returns list sorted newest first.
    """
    d = _history_dir()
    if not d:
        return []

    entries = []
    now     = datetime.now(timezone.utc)

    for i in range(days):
        date = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        path = d / ("%s.jsonl" % date)
        if not path.exists():
            continue
        try:
            with path.open() as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        except Exception as e:
            log.warning("history.read_entries %s: %s", path, e)

    entries.sort(key=lambda x: x.get("submitted_at", ""), reverse=True)
    return entries
