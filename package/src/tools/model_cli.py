"""
model_cli.py -- Marigold model, cache, workflow, and status CLI.

Commands:
    download-weights    Download model weights from HuggingFace to the local cache.
    inspect-cache       Report cache state against models.yaml.
    run-model           Load a model and run one inference pass.
    test-models         Run built-in fixture inferences against one or all models.
    build-catalogue     Merge models.yaml with cache state for S3 serving.
    workflow run        Execute a workflow YAML file locally (in-process).
    workflow test       Test workflow YAML files locally (in-process).
    workflow add        Create a workflow template via the API.
    workflow list       List workflow templates via the API.
    workflow submit     Submit a workflow execution via the API.
    workflow tail       Poll and stream workflow execution status.
    status              Live dashboard of models, queues, and executions.

Environment (or .marigold-env in cwd):
    CACHE_DIR           Path to local model cache (default: /mnt/efs/cache)
    MODELS_YAML_PATH    Path to models.yaml (required for cache commands)
    HF_TOKEN            HuggingFace token for gated models
    LOG_LEVEL           Logging verbosity (default: INFO)
    API_BASE            Marigold API base URL (required for remote commands)
    API_KEY             Marigold API key (required for remote commands)

Examples:
    python3 model_cli.py download-weights
    python3 model_cli.py inspect-cache --json > /tmp/cache_state.json
    python3 model_cli.py workflow add my-pipeline --spec pipeline.yaml
    python3 model_cli.py workflow submit my-pipeline --input text=hello
    python3 model_cli.py workflow submit my-pipeline --input text=hello --tail
    python3 model_cli.py workflow tail my-pipeline 20260501T132250-11ce
    python3 model_cli.py status
    python3 model_cli.py status --watch


# add the instruct-smoke template from a file
python3 model_cli.py workflow add instruct-smoke --spec workflows/instruct_smoke.yaml

# submit a run by name
python3 model_cli.py workflow submit instruct-smoke

# tail it (paste execution_id from submit output)
python3 model_cli.py workflow tail c05a3809bf871a38cafda8ee868c8625 20260501T132250-11ce

# one-shot status
python3 model_cli.py status

# live refresh
python3 model_cli.py status --watch
"""

import argparse
import json
import logging
import os
import resource
import struct
import sys
import time
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("model-cli")

# suppress noisy HTTP request logging from huggingface_hub and its dependencies
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("huggingface_hub").setLevel(logging.WARNING)
logging.getLogger("huggingface_hub.utils").setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

def _load_env(path: str = ".marigold-env"):
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

_load_env()


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class CliError(Exception):
    """Raised at the point of failure inside any command function.

    Caught once in main(), which logs the message and exits non-zero.
    """
    pass


CommandResult = tuple[dict, bool]


# ---------------------------------------------------------------------------
# Config context -- model catalogue commands
# ---------------------------------------------------------------------------

@dataclass
class ModelCatalogueContext:
    models: list
    cache_path: Path

    @classmethod
    def load(cls, model_name_filter: Optional[str] = None) -> "ModelCatalogueContext":
        try:
            import yaml
        except ImportError:
            raise CliError("pyyaml is required: pip install pyyaml")

        yaml_path = os.environ.get("MODELS_YAML_PATH", "")
        if not yaml_path:
            raise CliError("MODELS_YAML_PATH is required")

        path = Path(yaml_path)
        if not path.exists():
            raise CliError("models yaml not found: %s" % yaml_path)

        with open(path) as fh:
            config = yaml.safe_load(fh)

        all_models = config.get("models", [])
        if not all_models:
            raise CliError("no models found in config")

        if model_name_filter:
            models = [m for m in all_models if m["name"] == model_name_filter]
            if not models:
                raise CliError("'%s' not found in models.yaml" % model_name_filter)
        else:
            models = all_models

        return cls(
            models=models,
            cache_path=Path(os.getenv("CACHE_DIR", "/mnt/efs/cache")),
        )


# ---------------------------------------------------------------------------
# API client -- remote workflow and status commands
# ---------------------------------------------------------------------------

class MarigoldClient:
    """Minimal HTTP client for the Marigold workflow API."""

    def __init__(self):
        self.base = os.environ.get("API_BASE", "").rstrip("/")
        self.key  = os.environ.get("API_KEY", "")

        if not self.base:
            raise CliError("API_BASE is required (set in .marigold-env or environment)")
        if not self.key:
            raise CliError("API_KEY is required (set in .marigold-env or environment)")

        try:
            import requests as _requests
            self._requests = _requests
        except ImportError:
            raise CliError("requests is required: pip install requests")

    @property
    def _headers(self) -> dict:
        return {"x-api-key": self.key, "Content-Type": "application/json"}

    def get(self, path: str) -> dict:
        r = self._requests.get(
            "%s%s" % (self.base, path),
            headers=self._headers,
            timeout=15,
        )
        r.raise_for_status()
        return r.json()

    def post(self, path: str, body: dict) -> dict:
        r = self._requests.post(
            "%s%s" % (self.base, path),
            headers=self._headers,
            json=body,
            timeout=15,
        )
        r.raise_for_status()
        return r.json()

    def delete(self, path: str) -> dict:
        r = self._requests.delete(
            "%s%s" % (self.base, path),
            headers=self._headers,
            timeout=15,
        )
        r.raise_for_status()
        return r.json()

    # ---------------------------------------------------------------------------
    # Workflow API
    # ---------------------------------------------------------------------------

    def list_templates(self) -> list:
        return self.get("/workflows").get("templates", [])

    def get_template_by_name(self, name: str) -> Optional[dict]:
        """Return the most recently created template with the given name."""
        templates = self.list_templates()
        matches = [t for t in templates if t["name"] == name]
        if not matches:
            return None
        return sorted(matches, key=lambda t: t["created_at"], reverse=True)[0]

    def create_template(self, name: str, spec: str) -> dict:
        return self.post("/workflows", {"name": name, "spec": spec})

    def submit_execution(self, workflow_id: str, inputs: dict) -> dict:
        return self.post("/workflows/%s/run" % workflow_id, {"inputs": inputs})

    def get_execution(self, workflow_id: str, execution_id: str) -> dict:
        return self.get("/workflows/%s/executions/%s" % (workflow_id, execution_id))

    def get_steps(self, workflow_id: str, execution_id: str) -> list:
        return self.get(
            "/workflows/%s/executions/%s/steps" % (workflow_id, execution_id)
        ).get("steps", [])

    def get_models(self) -> dict:
        try:
            return self.get("/models.json")
        except Exception:
            return {}


# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------

def _peak_memory_mb() -> float:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    if sys.platform == "darwin":
        return usage.ru_maxrss / (1024 * 1024)
    return usage.ru_maxrss / 1024


def _model_cache_size_gb(model_name: str, cache_path: Path) -> float:
    cache_dir = cache_path / ("models--" + model_name.replace("/", "--"))
    if not cache_dir.exists():
        return 0.0
    return sum(
        f.stat().st_size for f in cache_dir.rglob("*") if f.is_file()
    ) / (1024 ** 3)


def _placeholder_image_b64() -> str:
    import base64
    def png_chunk(name: bytes, data: bytes) -> bytes:
        c = zlib.crc32(name + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", c)
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\xff\x00\x00")
    png = (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", ihdr)
        + png_chunk(b"IDAT", idat)
        + png_chunk(b"IEND", b"")
    )
    return base64.b64encode(png).decode()


def _inference_fixtures() -> dict:
    image = _placeholder_image_b64()
    return {
        "instruct":        {"messages": [{"role": "user", "content": "Reply with one word: hello"}]},
        "text-embedding":  {"input": "The quick brown fox jumps over the lazy dog"},
        "image-embedding": {"input": image},
        "tts":             {"text": "Hello world", "language_code": "en-gb"},
        "txt2img":         {"prompt": "A red circle on a white background"},
        "txt2audio":       {"prompt": "A gentle acoustic guitar melody"},
        "img2txt":         {"input": image},
        "depth":           {"input": image},
        "img2mask":        {"input": image},
        "text-eval":       {"text": "I love this product"},
        "text-similarity": {
            "text_a": "The cat sat on the mat",
            "text_b": "A cat was sitting on a mat",
        },
        "image-eval":      {"image": image},
        "image-text-eval": {"image": image, "text": "a red circle"},
    }


def _elapsed(created_at: str) -> str:
    try:
        from datetime import datetime, timezone
        fmt = "%Y-%m-%dT%H:%M:%SZ"
        t0  = datetime.strptime(created_at, fmt).replace(tzinfo=timezone.utc)
        secs = int((datetime.now(timezone.utc) - t0).total_seconds())
        if secs < 60:
            return "%ds" % secs
        if secs < 3600:
            return "%dm%ds" % (secs // 60, secs % 60)
        return "%dh%dm" % (secs // 3600, (secs % 3600) // 60)
    except Exception:
        return "?"


# ---------------------------------------------------------------------------
# Local model commands
# ---------------------------------------------------------------------------

def download_weights(model_name_filter: Optional[str]) -> CommandResult:
    """Download and cache model weights from HuggingFace to the EFS cache."""
    from tools.model_cache_shared import run_build

    ctx = ModelCatalogueContext.load(model_name_filter)
    hf_token = os.environ.get("HF_TOKEN", "")

    build_result = run_build(
        ctx.models, ctx.cache_path, hf_token, prune=model_name_filter is None
    )
    result = {
        "cached":   build_result.cached,
        "pruned":   build_result.pruned,
        "errors":   build_result.errors,
        "total_gb": round(sum(
            _model_cache_size_gb(n, ctx.cache_path) for n in build_result.cached
        ), 3),
    }
    return result, not build_result.errors


def inspect_cache(as_json: bool) -> CommandResult:
    """Report cache state against the models declared in models.yaml."""
    from tools.model_cache_shared import inspect_to_dict, run_inspect

    ctx   = ModelCatalogueContext.load()
    state = inspect_to_dict(ctx.models, ctx.cache_path)
    if not as_json:
        run_inspect(state)
    return state, not state["anomalies"]


def run_model_inference(model_name: str, model_type: str, request_source: str) -> CommandResult:
    """Load a model and run one inference pass against a supplied request."""
    import models as _models
    from shared.registry import _SPECS

    raw = sys.stdin.read() if request_source == "-" else open(request_source).read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        raise CliError("request is not valid JSON: %s" % e)

    _models.load_all()
    if model_type not in _SPECS:
        raise CliError("unknown model type '%s'. known: %s" % (model_type, sorted(_SPECS)))

    payload["model"] = model_name
    t_load = time.perf_counter()
    try:
        handler = _SPECS[model_type].handler_class(model_name)
    except Exception as e:
        raise CliError("model load failed for '%s': %s" % (model_name, e))
    load_duration = time.perf_counter() - t_load

    t_infer = time.perf_counter()
    try:
        inference_result = handler.process(user_id="cli", message_id="cli-run", request=payload)
    except Exception as e:
        raise CliError("inference failed: %s" % e)
    infer_duration = time.perf_counter() - t_infer

    return {
        "model":             model_name,
        "type":              model_type,
        "load_seconds":      round(load_duration, 3),
        "inference_seconds": round(infer_duration, 3),
        "peak_memory_mb":    round(_peak_memory_mb(), 1),
        "cache_size_gb":     round(_model_cache_size_gb(model_name, Path(os.getenv("CACHE_DIR", "/mnt/efs/cache"))), 3),
        "output": inference_result.model_dump() if hasattr(inference_result, "model_dump") else str(inference_result),
    }, True


def test_models(model_name_filter: Optional[str]) -> CommandResult:
    """Run built-in fixture inferences against one or all declared models."""
    import models as _models
    from shared.registry import _SPECS

    ctx = ModelCatalogueContext.load(model_name_filter)
    _models.load_all()
    fixtures = _inference_fixtures()
    results  = []

    for entry in ctx.models:
        name       = entry["name"]
        model_type = entry["type"]

        if model_type not in fixtures:
            results.append({"model": name, "type": model_type, "status": "skipped", "reason": "no fixture"})
            continue
        if model_type not in _SPECS:
            results.append({"model": name, "type": model_type, "status": "skipped", "reason": "not registered"})
            continue

        payload = {**fixtures[model_type], "model": name}
        t_load  = time.perf_counter()
        try:
            handler = _SPECS[model_type].handler_class(name)
        except Exception as e:
            results.append({"model": name, "type": model_type, "status": "error", "stage": "load", "error": str(e)})
            continue
        load_duration = time.perf_counter() - t_load

        t_infer = time.perf_counter()
        try:
            handler.process(user_id="cli", message_id="cli-test", request=payload)
        except Exception as e:
            results.append({"model": name, "type": model_type, "status": "error", "stage": "inference", "error": str(e)})
            continue
        infer_duration = time.perf_counter() - t_infer

        results.append({
            "model":             name,
            "type":              model_type,
            "status":            "ok",
            "load_seconds":      round(load_duration, 3),
            "inference_seconds": round(infer_duration, 3),
            "peak_memory_mb":    round(_peak_memory_mb(), 1),
            "cache_size_gb":     round(_model_cache_size_gb(name, ctx.cache_path), 3),
        })

    return {"results": results}, not any(r["status"] == "error" for r in results)


def build_public_catalogue(models_yaml_path: str, cache_state_path: Optional[str]) -> CommandResult:
    """Merge models.yaml with cache state for S3 serving."""
    try:
        import yaml
        with open(models_yaml_path) as fh:
            models_list = yaml.safe_load(fh).get("models", [])
    except Exception as e:
        raise CliError("failed to read models yaml: %s" % e)

    cache_state = None
    if cache_state_path:
        try:
            with open(cache_state_path) as fh:
                cache_state = json.load(fh)
        except Exception as e:
            raise CliError("failed to read cache state file: %s" % e)

    models_out = []
    for entry in models_list:
        cached = None
        if cache_state:
            m = cache_state["models"].get(entry["name"])
            cached = m["status"] == "ok" if m else False
        models_out.append({
            "name":     entry["name"],
            "type":     entry["type"],
            "provider": entry["provider"],
            "input":    entry["input"],
            "output":   entry["output"],
            "cached":   cached,
        })

    return {
        "models":         models_out,
        "cache_state_at": cache_state["inspected_at"] if cache_state else None,
    }, True


# ---------------------------------------------------------------------------
# Local workflow commands
# ---------------------------------------------------------------------------

def run_workflow_locally(yaml_path: str, inputs: dict) -> CommandResult:
    """Execute a workflow YAML file locally using an in-process backend."""
    import runfox as rfx
    from runfox.backend import InMemoryStore, InProcessRunner, InProcessWorker
    from tools.workflow_executor import execute

    path = Path(yaml_path)
    if not path.exists():
        raise CliError("workflow file not found: %s" % yaml_path)

    with open(path) as fh:
        spec = fh.read()

    runner    = InProcessRunner()
    worker    = InProcessWorker(runner, execute)
    backend   = rfx.Backend(store=InMemoryStore(), runner=runner)
    wf        = rfx.Workflow.from_yaml(spec, backend, inputs=inputs)
    wf_result = wf.run(worker=worker)
    record    = backend.load(wf.id)

    return {
        "workflow": path.name,
        "inputs":   inputs,
        "outcome":  wf_result.outcome if hasattr(wf_result, "outcome") else str(wf_result),
        "trace": {
            "status": record.status.value,
            "state":  record.state,
            "steps":  {
                op: {"status": s.status.value, "output": s.output, "run_id": s.run_id}
                for op, s in record.steps.items()
            },
        },
    }, True


def test_workflow_specs(target: str) -> CommandResult:
    """Run one or all workflow YAML files found at target."""
    import runfox as rfx
    from runfox.backend import InMemoryStore, InProcessRunner, InProcessWorker
    from tools.workflow_executor import execute

    target_path = Path(target)
    if not target_path.exists():
        raise CliError("target not found: %s" % target)

    yaml_files = sorted(target_path.glob("*.yaml")) if target_path.is_dir() else [target_path]
    if not yaml_files:
        raise CliError("no .yaml files found in %s" % target)

    results = []
    for path in yaml_files:
        try:
            with open(path) as fh:
                spec = fh.read()
            runner    = InProcessRunner()
            worker    = InProcessWorker(runner, execute)
            backend   = rfx.Backend(store=InMemoryStore(), runner=runner)
            wf        = rfx.Workflow.from_yaml(spec, backend, inputs={})
            wf_result = wf.run(worker=worker)
            record    = backend.load(wf.id)
            results.append({
                "workflow": path.name,
                "status":   "ok",
                "outcome":  wf_result.outcome if hasattr(wf_result, "outcome") else str(wf_result),
                "trace": {
                    "status": record.status.value,
                    "steps":  {op: {"status": s.status.value, "run_id": s.run_id} for op, s in record.steps.items()},
                },
            })
        except Exception as e:
            results.append({"workflow": path.name, "status": "error", "error": str(e)})

    return {"results": results}, not any(r["status"] == "error" for r in results)


# ---------------------------------------------------------------------------
# Remote workflow commands
# ---------------------------------------------------------------------------

def workflow_add(name: str, spec_path: str) -> CommandResult:
    """Create a workflow template via the API.

    spec_path is a path to a YAML file or '-' to read from stdin.
    """
    if spec_path == "-":
        spec = sys.stdin.read()
    else:
        path = Path(spec_path)
        if not path.exists():
            raise CliError("spec file not found: %s" % spec_path)
        spec = path.read_text()

    client = MarigoldClient()
    result = client.create_template(name, spec)
    return result, True


def workflow_list() -> CommandResult:
    """List workflow templates via the API."""
    client    = MarigoldClient()
    templates = client.list_templates()
    return {"templates": templates, "count": len(templates)}, True


def workflow_submit(name_or_id: str, inputs: dict, tail: bool = False) -> CommandResult:
    """Submit a workflow execution via the API.

    name_or_id may be a workflow name (most recently created template with
    that name is used) or a workflow_id directly.
    """
    client = MarigoldClient()

    # If it looks like a hash (32 hex chars) treat it as a workflow_id directly
    if len(name_or_id) == 32 and all(c in "0123456789abcdef" for c in name_or_id):
        workflow_id = name_or_id
    else:
        template = client.get_template_by_name(name_or_id)
        if template is None:
            raise CliError("no template found with name '%s'" % name_or_id)
        workflow_id = template["workflow_id"]

    result = client.submit_execution(workflow_id, inputs)
    log.info("submitted: workflow_id=%s execution_id=%s",
             result.get("workflow_id"), result.get("execution_id"))

    if tail:
        return workflow_tail(
            result["workflow_id"],
            result["execution_id"],
        )

    return result, True


def workflow_tail(
    workflow_id: str,
    execution_id: str,
    poll_interval: int = 3,
    timeout: int = 300,
) -> CommandResult:
    """Poll and stream workflow execution status until terminal state.

    Prints step progress on each poll. Exits when the execution reaches
    complete, halted, or cancelled, or when timeout is exceeded.
    """
    client    = MarigoldClient()
    deadline  = time.time() + timeout
    last_step_status: dict = {}

    print("tailing %s / %s" % (workflow_id, execution_id))
    print()

    while time.time() < deadline:
        try:
            execution = client.get_execution(workflow_id, execution_id)
            steps     = client.get_steps(workflow_id, execution_id)
        except Exception as e:
            log.warning("poll failed: %s", e)
            time.sleep(poll_interval)
            continue

        status   = execution.get("status", "?")
        elapsed  = _elapsed(execution.get("created_at", ""))
        progress = execution.get("progress", {})

        # print step changes
        for step in steps:
            key        = step.get("step_id", step.get("op", "?"))
            new_status = step.get("status", "?")
            if last_step_status.get(key) != new_status:
                print("  step %-30s  %s" % (step.get("op", key)[:30], new_status))
                last_step_status[key] = new_status

        # print execution status line
        print("\r  status=%-12s  elapsed=%-8s  steps=%d/%d   " % (
            status,
            elapsed,
            progress.get("complete", 0),
            progress.get("total", 0),
        ), end="", flush=True)

        if status in ("complete", "halted", "cancelled"):
            print()
            print()
            outcome = execution.get("outcome")
            if outcome:
                print("outcome:")
                print(json.dumps(outcome, indent=2))
            return execution, status == "complete"

        time.sleep(poll_interval)

    print()
    raise CliError("timed out after %ds waiting for execution to complete" % timeout)


# ---------------------------------------------------------------------------
# Status dashboard
# ---------------------------------------------------------------------------

def status_dashboard(watch: bool) -> CommandResult:
    """Compact live dashboard showing models, queues, and API health.

    Uses rich if available for a cleaner display.
    Falls back to plain text.
    """
    try:
        from rich.console import Console
        from rich.table   import Table
        from rich.live    import Live
        from rich.panel   import Panel
        from rich.columns import Columns
        has_rich = True
    except ImportError:
        has_rich = False

    def render_plain():
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        client = MarigoldClient()
        lines  = ["", "Marigold Status  %s" % now, ""]

        # models
        models_data = client.get_models()
        models      = models_data.get("models", [])
        cached      = sum(1 for m in models if m.get("cached") is True)
        missing     = sum(1 for m in models if m.get("cached") is False)
        lines.append("Models: %d cached  %d missing  (state at %s)" % (
            cached, missing, models_data.get("cache_state_at", "unknown")
        ))

        by_type = {}
        for m in models:
            by_type.setdefault(m["type"], []).append(m)
        for t in sorted(by_type):
            ms = by_type[t]
            nc = sum(1 for m in ms if m.get("cached") is True)
            lines.append("  %-22s %d/%d" % (t, nc, len(ms)))

        lines.append("")

        # templates
        templates = client.list_templates()
        lines.append("Templates: %d registered" % len(templates))
        for t in sorted(templates, key=lambda x: x.get("created_at", ""), reverse=True)[:5]:
            lines.append("  %-40s %s" % (t["name"][:40], t["workflow_id"]))

        lines.append("")
        return "\n".join(lines), {}, True

    def render_rich():
        from datetime import datetime, timezone
        from rich.console import Console
        from rich.table   import Table
        from rich.panel   import Panel

        console = Console()
        client  = MarigoldClient()
        now     = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # models table
        models_data = client.get_models()
        models      = models_data.get("models", [])
        by_type     = {}
        for m in models:
            by_type.setdefault(m["type"], []).append(m)

        model_table = Table(title="Models  (state at %s)" % models_data.get("cache_state_at", "unknown"),
                            show_header=True, header_style="bold")
        model_table.add_column("Type",   style="cyan",  no_wrap=True)
        model_table.add_column("Cached", justify="right")
        model_table.add_column("Total",  justify="right")

        for t in sorted(by_type):
            ms = by_type[t]
            nc = sum(1 for m in ms if m.get("cached") is True)
            colour = "green" if nc == len(ms) else "yellow" if nc > 0 else "red"
            model_table.add_row(t, "[%s]%d[/%s]" % (colour, nc, colour), str(len(ms)))

        # templates table
        templates      = client.list_templates()
        template_table = Table(title="Templates (%d)" % len(templates),
                               show_header=True, header_style="bold")
        template_table.add_column("Name",        style="cyan", no_wrap=True, max_width=35)
        template_table.add_column("ID",          no_wrap=True)
        template_table.add_column("Created",     no_wrap=True)

        for t in sorted(templates, key=lambda x: x.get("created_at", ""), reverse=True)[:10]:
            template_table.add_row(
                t["name"][:35],
                t["workflow_id"],
                t.get("created_at", "?"),
            )

        console.print()
        console.print("[bold]Marigold Status[/bold]  [cyan]%s[/cyan]  %s" % (
            os.environ.get("API_BASE", ""), now
        ))
        console.print()
        console.print(model_table)
        console.print()
        console.print(template_table)
        console.print()

        return {}, {}, True

    if watch:
        print("watching (Ctrl-C to stop)...")
        try:
            while True:
                os.system("clear")
                if has_rich:
                    render_rich()
                else:
                    text, _, _ = render_plain()
                    print(text)
                time.sleep(10)
        except KeyboardInterrupt:
            pass
        return {}, True
    else:
        if has_rich:
            render_rich()
            return {}, True
        else:
            text, result, success = render_plain()
            print(text)
            return result, success


# ---------------------------------------------------------------------------
# Input parsing
# ---------------------------------------------------------------------------

def parse_workflow_inputs(pairs: list) -> dict:
    """Parse key=value pairs into a workflow inputs dict.

    Values are JSON-decoded where possible.
    """
    result = {}
    for pair in pairs:
        if "=" not in pair:
            raise CliError("input must be key=value, got: %s" % pair)
        k, v = pair.split("=", 1)
        try:
            result[k] = json.loads(v)
        except json.JSONDecodeError:
            result[k] = v
    return result


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Marigold model, cache, workflow, and status CLI")
    parser.add_argument(
        "--json", action="store_true", dest="as_json",
        help="emit structured JSON to stdout",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # download-weights
    dw = sub.add_parser("download-weights", help="download model weights to local cache")
    dw.add_argument("model_name", nargs="?", default=None)

    # inspect-cache
    sub.add_parser("inspect-cache", help="report cache state against models.yaml")

    # run-model
    rm = sub.add_parser("run-model", help="load a model and run one inference pass")
    rm.add_argument("model_name")
    rm.add_argument("model_type")
    rm.add_argument("--request", default="-")

    # test-models
    tm = sub.add_parser("test-models", help="run fixture inferences against declared models")
    tm.add_argument("model_name", nargs="?", default=None)

    # build-catalogue
    bc = sub.add_parser("build-catalogue", help="merge models.yaml with cache state for S3")
    bc.add_argument("models_yaml_file")
    bc.add_argument("--cache-state", default=None, metavar="FILE")

    # workflow
    wf     = sub.add_parser("workflow", help="local and remote workflow commands")
    wf_sub = wf.add_subparsers(dest="workflow_command", required=True)

    # workflow run (local)
    wf_run = wf_sub.add_parser("run", help="execute a workflow YAML file locally (in-process)")
    wf_run.add_argument("workflow_file", help="path to workflow YAML")
    wf_run.add_argument("--input", dest="inputs", action="append", default=[])

    # workflow test (local)
    wf_test = wf_sub.add_parser("test", help="test workflow YAML files locally (in-process)")
    wf_test.add_argument("target", help="path to .yaml file or directory")

    # workflow add (remote)
    wf_add = wf_sub.add_parser("add", help="create a workflow template via the API")
    wf_add.add_argument("name", help="template name")
    wf_add.add_argument("--spec", default="-", metavar="FILE",
                        help="path to workflow YAML, or - for stdin (default: -)")

    # workflow list (remote)
    wf_sub.add_parser("list", help="list workflow templates via the API")

    # workflow submit (remote)
    wf_submit = wf_sub.add_parser("submit", help="submit a workflow execution via the API")
    wf_submit.add_argument("name_or_id", help="template name or workflow_id")
    wf_submit.add_argument("--input", dest="inputs", action="append", default=[])
    wf_submit.add_argument("--tail", action="store_true", help="automatically tail the execution after submitting")

    # workflow tail (remote)
    wf_tail = wf_sub.add_parser("tail", help="stream workflow execution status")
    wf_tail.add_argument("workflow_id")
    wf_tail.add_argument("execution_id")
    wf_tail.add_argument("--timeout", type=int, default=300)
    wf_tail.add_argument("--interval", type=int, default=3)

    # status
    st = sub.add_parser("status", help="live dashboard of models and workflows")
    st.add_argument("--watch", action="store_true", help="refresh every 10 seconds")

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = build_parser()
    args   = parser.parse_args()

    try:
        if args.command == "download-weights":
            result, success = download_weights(args.model_name)

        elif args.command == "inspect-cache":
            result, success = inspect_cache(as_json=args.as_json)

        elif args.command == "run-model":
            result, success = run_model_inference(args.model_name, args.model_type, args.request)

        elif args.command == "test-models":
            result, success = test_models(args.model_name)

        elif args.command == "build-catalogue":
            result, success = build_public_catalogue(args.models_yaml_file, args.cache_state)

        elif args.command == "workflow":
            wc = args.workflow_command
            if wc == "run":
                result, success = run_workflow_locally(
                    args.workflow_file, parse_workflow_inputs(args.inputs)
                )
            elif wc == "test":
                result, success = test_workflow_specs(args.target)
            elif wc == "add":
                result, success = workflow_add(args.name, args.spec)
            elif wc == "list":
                result, success = workflow_list()
            elif wc == "submit":
                result, success = workflow_submit(
                    args.name_or_id, parse_workflow_inputs(args.inputs)
                )
            elif wc == "tail":
                result, success = workflow_tail(
                    args.workflow_id, args.execution_id,
                    poll_interval=args.interval,
                    timeout=args.timeout,
                )
            else:
                result, success = {}, False

        elif args.command == "status":
            result, success = status_dashboard(watch=args.watch)

        else:
            result, success = {}, False

    except CliError as e:
        log.error("%s", e)
        sys.exit(1)

    # status and tail own their output entirely
    if args.command in ("status",):
        sys.exit(0 if success else 1)

    # inspect-cache in human mode already printed its table
    if args.command == "inspect-cache" and not args.as_json:
        sys.exit(0 if success else 1)

    # everything else: print JSON
    if result:
        print(json.dumps(result, indent=2))

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
