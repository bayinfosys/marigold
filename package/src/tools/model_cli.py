"""Local model development CLI.

Usage:
    model_cli.py run <model-name> <model-type> [--request <file|->]
    model_cli.py test [<model-name>]

Environment:
    CACHE_DIR           path to local model cache (default: /mnt/efs/cache)
    MODELS_YAML_PATH    path to models.yaml (required for test)
    OUTPUT_DIR          path to write binary outputs (default: /tmp/model-cli-out)
    LOG_LEVEL           logging verbosity (default: INFO)

Examples:
    echo '{"messages":[{"role":"user","content":"hello"}]}' | \
        model_cli.py run qwen/qwen2-0.5b-instruct instruct --request -
    model_cli.py test qwen/qwen2-0.5b-instruct
    model_cli.py test
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
from pathlib import Path

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("model-cli")


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def memory_peak_mb() -> float:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    if sys.platform == "darwin":
        return usage.ru_maxrss / (1024 * 1024)
    return usage.ru_maxrss / 1024


def cache_size_gb(model_name: str, cache_dir: str) -> float:
    cache_name = "models--" + model_name.replace("/", "--")
    path = Path(cache_dir) / cache_name
    if not path.exists():
        return 0.0
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return total / (1024**3)


def get_config() -> dict:
    try:
        import yaml
    except ImportError:
        log.error("pyyaml is required: pip install pyyaml")
        sys.exit(1)

    yaml_path = os.environ.get("MODELS_YAML_PATH", "")
    if not yaml_path:
        log.error("MODELS_YAML_PATH is required")
        sys.exit(1)

    if not Path(yaml_path).exists():
        log.error("models yaml not found: %s", yaml_path)
        sys.exit(1)

    with open(yaml_path) as fh:
        return yaml.safe_load(fh)


def _placeholder_image_b64() -> str:
    """1x1 red PNG as base64, sufficient to exercise image model handlers."""
    import base64

    def png_chunk(name: bytes, data: bytes) -> bytes:
        import zlib as _zlib

        c = _zlib.crc32(name + data) & 0xFFFFFFFF
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


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


def _fixtures() -> dict:
    image = _placeholder_image_b64()
    return {
        "instruct": {
            "messages": [{"role": "user", "content": "Reply with one word: hello"}]
        },
        "text-embedding": {"input": "The quick brown fox jumps over the lazy dog"},
        "image-embedding": {"input": image},
        "tts": {"text": "Hello world", "language_code": "en-gb"},
        "txt2img": {"prompt": "A red circle on a white background"},
        "txt2audio": {"prompt": "A gentle acoustic guitar melody"},
        "img2txt": {"input": image},
        "depth": {"input": image},
        "img2mask": {"input": image},
        "text-eval": {"text": "I love this product"},
        "text-similarity": {
            "text_a": "The cat sat on the mat",
            "text_b": "A cat was sitting on a mat",
        },
        "image-eval": {"image": image},
        "image-text-eval": {"image": image, "text": "a red circle"},
    }


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_cache(model_name: str | None):
    from tools.model_cache_shared import print_build_summary, run_build, run_inspect

    config = get_config()
    all_models = config.get("models", [])

    if not all_models:
        log.error("no models found in config")
        sys.exit(1)

    cache_dir = os.getenv("CACHE_DIR", "/mnt/efs/cache")
    hf_token = os.environ.get("HF_TOKEN", "")
    cache_path = Path(cache_dir)

    if model_name:
        targets = [m for m in all_models if m["name"] == model_name]
        if not targets:
            log.error("'%s' not found in models.yaml", model_name)
            sys.exit(1)
    else:
        targets = all_models

    result = run_build(targets, cache_path, hf_token, prune=model_name is None)
    print_build_summary(result, cache_path)
    sys.exit(1 if result.errors else 0)


def cmd_inspect():
    from tools.model_cache_shared import run_inspect

    config = get_config()
    all_models = config.get("models", [])
    cache_dir = os.getenv("CACHE_DIR", "/mnt/efs/cache")
    run_inspect(all_models, Path(cache_dir))
    sys.exit(0)


def cmd_run(model_name: str, model_type: str, request_source: str, output_dir: str):
    import models
    from shared.registry import _SPECS

    models.load_all()

    if model_type not in _SPECS:
        log.error("unknown model type '%s'. known: %s", model_type, sorted(_SPECS))
        sys.exit(1)

    spec = _SPECS[model_type]

    if request_source == "-":
        raw = sys.stdin.read()
    else:
        with open(request_source) as fh:
            raw = fh.read()

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        log.error("request is not valid JSON: %s", e)
        sys.exit(1)

    payload["model"] = model_name

    log.info("loading %s (%s)", model_name, model_type)
    t_load = time.perf_counter()

    try:
        handler = spec.handler_class(model_name)
    except Exception as e:
        log.error("model load failed: %s", e)
        sys.exit(1)

    load_duration = time.perf_counter() - t_load
    log.info("loaded in %.2fs", load_duration)

    log.info("running inference")
    t_run = time.perf_counter()

    try:
        result = handler.process(user_id="cli", message_id="cli-test", request=payload)
    except Exception as e:
        log.error("inference failed: %s", e)
        sys.exit(1)

    run_duration = time.perf_counter() - t_run
    cache_dir = os.getenv("CACHE_DIR", "/mnt/efs/cache")

    output = {
        "model": model_name,
        "type": model_type,
        "load_seconds": round(load_duration, 3),
        "inference_seconds": round(run_duration, 3),
        "peak_memory_mb": round(memory_peak_mb(), 1),
        "cache_size_gb": round(cache_size_gb(model_name, cache_dir), 3),
        "result": result.model_dump() if hasattr(result, "model_dump") else str(result),
    }

    print(json.dumps(output, indent=2))


def cmd_test(model_name: str | None, output_dir: str):
    import models
    from shared.registry import _SPECS

    models.load_all()

    config = get_config()
    all_models = config.get("models", [])

    if model_name:
        targets = [m for m in all_models if m["name"] == model_name]
        if not targets:
            log.error("'%s' not found in models.yaml", model_name)
            sys.exit(1)
    else:
        targets = all_models

    fixtures = _fixtures()
    cache_dir = os.getenv("CACHE_DIR", "/mnt/efs/cache")
    results = []

    for entry in targets:
        name = entry["name"]
        model_type = entry["type"]

        if model_type not in fixtures:
            log.warning("no fixture for type '%s', skipping %s", model_type, name)
            results.append(
                {
                    "model": name,
                    "type": model_type,
                    "status": "skipped",
                    "reason": "no fixture",
                }
            )
            continue

        if model_type not in _SPECS:
            log.warning("type '%s' not registered, skipping %s", model_type, name)
            results.append(
                {
                    "model": name,
                    "type": model_type,
                    "status": "skipped",
                    "reason": "not registered",
                }
            )
            continue

        payload = dict(fixtures[model_type])
        payload["model"] = name

        spec = _SPECS[model_type]

        log.info("testing %s (%s)", name, model_type)
        t_load = time.perf_counter()

        try:
            handler = spec.handler_class(name)
        except Exception as e:
            log.error("load failed: %s", e)
            results.append(
                {
                    "model": name,
                    "type": model_type,
                    "status": "error",
                    "stage": "load",
                    "error": str(e),
                }
            )
            continue

        load_duration = time.perf_counter() - t_load
        t_run = time.perf_counter()

        try:
            result = handler.process(
                user_id="cli", message_id="cli-test", request=payload
            )
        except Exception as e:
            log.error("inference failed: %s", e)
            results.append(
                {
                    "model": name,
                    "type": model_type,
                    "status": "error",
                    "stage": "inference",
                    "error": str(e),
                }
            )
            continue

        run_duration = time.perf_counter() - t_run

        results.append(
            {
                "model": name,
                "type": model_type,
                "status": "ok",
                "load_seconds": round(load_duration, 3),
                "inference_seconds": round(run_duration, 3),
                "peak_memory_mb": round(memory_peak_mb(), 1),
                "cache_size_gb": round(cache_size_gb(name, cache_dir), 3),
            }
        )

        log.info("ok: %s", name)

    print(json.dumps(results, indent=2))

    failed = [r for r in results if r["status"] == "error"]
    sys.exit(1 if failed else 0)


def parse_inputs(pairs: list[str]) -> dict:
    result = {}
    for pair in pairs:
        if "=" not in pair:
            log.error("input must be key=value, got: %s", pair)
            sys.exit(1)
        k, v = pair.split("=", 1)
        # attempt JSON parse for booleans, numbers, objects
        try:
            result[k] = json.loads(v)
        except json.JSONDecodeError:
            result[k] = v
    return result


def cmd_run_workflow(yaml_path: str, inputs: dict, debug: bool = False):
    import runfox as rfx
    from runfox.backend import InMemoryStore, InProcessRunner, InProcessWorker
    from tools.workflow_executor import execute

    path = Path(yaml_path)
    if not path.exists():
        log.error("workflow file not found: %s", yaml_path)
        sys.exit(1)

    log.info("running %s with inputs %s", path.name, inputs)

    with open(path) as fh:
        spec = fh.read()

    runner  = InProcessRunner()
    worker  = InProcessWorker(runner, execute)
    backend = rfx.Backend(store=InMemoryStore(), runner=runner)
    wf      = rfx.Workflow.from_yaml(spec, backend, inputs=inputs)
    result  = wf.run(worker=worker)

    if debug:
        record = backend.load(wf.id)
        debug_info = {
            "status": record.status.value,
            "steps": {
                op: {
                    "status": s.status.value,
                    "output": s.output,
                    "run_id": s.run_id,
                }
                for op, s in record.steps.items()
            },
            "state": record.state,
        }
        import sys
        print("--- debug ---", file=sys.stderr)
        print(json.dumps(debug_info, indent=2), file=sys.stderr)

    output = {
        "workflow": path.name,
        "inputs": inputs,
        "outcome": result.outcome if hasattr(result, "outcome") else str(result),
    }
    print(json.dumps(output, indent=2))


def cmd_test_workflow():
    workflows_dir = Path(__file__).parent / "workflows"
    test_cases = [
        ("single_step.yaml", {"text": "hello world"}),
        ("two_step_chain.yaml", {"text": "hello world"}),
        ("condition.yaml", {"flag": True}),
        ("condition.yaml", {"flag": False}),
    ]

    results = []
    for filename, inputs in test_cases:
        path = workflows_dir / filename
        if not path.exists():
            log.warning("workflow not found: %s", path)
            results.append(
                {"workflow": filename, "inputs": inputs, "status": "missing"}
            )
            continue

        try:
            import runfox as rfx
            from tools.workflow_executor import execute

            backend = rfx.InMemoryBackend(executor=execute)
            wf = rfx.Workflow.from_yaml(str(path), backend, inputs=inputs)
            result = wf.run()
            results.append(
                {
                    "workflow": filename,
                    "inputs": inputs,
                    "status": "ok",
                    "outcome": (
                        result.outcome if hasattr(result, "outcome") else str(result)
                    ),
                }
            )
            log.info("ok: %s %s", filename, inputs)
        except Exception as e:
            log.error("failed: %s %s -- %s", filename, inputs, e)
            results.append(
                {
                    "workflow": filename,
                    "inputs": inputs,
                    "status": "error",
                    "error": str(e),
                }
            )

    print(json.dumps(results, indent=2))
    failed = [r for r in results if r["status"] == "error"]
    sys.exit(1 if failed else 0)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Marigold local model CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    cache_p = sub.add_parser("cache", help="download model weights to local cache")
    cache_p.add_argument(
        "model_name",
        nargs="?",
        default=None,
        help="model name as in models.yaml; omit to cache all models",
    )

    sub.add_parser("inspect", help="report cache state against models.yaml")

    run_p = sub.add_parser("run", help="load a model and run one inference pass")
    run_p.add_argument("model_name")
    run_p.add_argument("model_type")
    run_p.add_argument(
        "--request",
        default="-",
        help="path to JSON request file, or - for stdin (default: -)",
    )
    run_p.add_argument(
        "--output-dir", default=os.getenv("OUTPUT_DIR", "/tmp/model-cli-out")
    )

    test_p = sub.add_parser(
        "test", help="run built-in fixtures against one or all models"
    )
    test_p.add_argument(
        "model_name",
        nargs="?",
        default=None,
        help="model name as in models.yaml; omit to test all models",
    )
    test_p.add_argument(
        "--output-dir", default=os.getenv("OUTPUT_DIR", "/tmp/model-cli-out")
    )

    workflow_p = sub.add_parser("workflow", help="run a workflow locally")
    workflow_sub = workflow_p.add_subparsers(dest="workflow_command", required=True)

    wf_run_p = workflow_sub.add_parser("run", help="run a single workflow")
    wf_run_p.add_argument("workflow", help="path to workflow YAML")
    wf_run_p.add_argument(
        "--input",
        dest="inputs",
        action="append",
        default=[],
        help="input as key=value (repeat for multiple)",
    )
    wf_run_p.add_argument("--debug", action="store_true", default=False)

    workflow_sub.add_parser("test", help="run all workflow test fixtures")

    args = parser.parse_args()

    if args.command == "cache":
        cmd_cache(args.model_name)

    if args.command == "run":
        cmd_run(args.model_name, args.model_type, args.request, args.output_dir)

    if args.command == "test":
        cmd_test(args.model_name, args.output_dir)

    if args.command == "inspect":
        cmd_inspect()

    if args.command == "workflow":
        if args.workflow_command == "run":
            cmd_run_workflow(args.workflow, parse_inputs(args.inputs), debug=args.debug)
        elif args.workflow_command == "test":
            cmd_test_workflow()


if __name__ == "__main__":
    main()
