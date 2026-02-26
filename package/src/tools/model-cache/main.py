"""
Model cache manager.

Subcommands:
  build      Cache all declared models, prune undeclared models, report changes.
  inspect    Report cache contents, sizes, and drift from the declared model list.

Usage:
  python3 main.py build
  python3 main.py inspect

Environment variables:

  Common:
    CACHE_DIR             Path for model cache (default: /mnt/efs/cache)
    HF_TOKEN              HuggingFace token for gated models
    CACHE_MODEL_SCRIPT    Path to cache_model.py (default: /opt/cache_model.py)

  AWS mode (default):
    MODELS_S3_BUCKET      S3 bucket containing models.json
    MODELS_S3_KEY         S3 key for models.json
    AWS_DEFAULT_REGION    AWS region (default: eu-west-2)

  Local mode (LOCAL_MODE=1):
    MODELS_YAML_PATH      Path to models.yaml on the local filesystem
"""

import json
import logging
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("cache-manager")

QUANTIZABLE_TYPES = {"instruct", "img2txt", "txt2img"}


# ---------------------------------------------------------------------------
# Configuration loading
# ---------------------------------------------------------------------------


def get_config() -> dict:
    """
    Load the model configuration.

    In local mode reads from a YAML file on disk.
    In AWS mode fetches models.json from S3.

    The LOCAL_MODE check is internal to this function -- callers receive
    a consistent dict regardless of the source.
    """
    if os.environ.get("LOCAL_MODE", "0") == "1":
        yaml_path = os.environ.get("MODELS_YAML_PATH", "")
        if not yaml_path:
            log.error("LOCAL_MODE requires MODELS_YAML_PATH to be set")
            sys.exit(1)

        try:
            import yaml
        except ImportError:
            log.error("pyyaml is required in local mode: pip install pyyaml")
            sys.exit(1)

        log.info("local mode: reading %s", yaml_path)
        with open(yaml_path) as fh:
            return yaml.safe_load(fh)

    import boto3

    region = os.environ.get("AWS_DEFAULT_REGION", "eu-west-2")
    bucket = os.environ["MODELS_S3_BUCKET"]
    key = os.environ["MODELS_S3_KEY"]

    log.info("fetching s3://%s/%s", bucket, key)
    s3 = boto3.client("s3", region_name=region)
    response = s3.get_object(Bucket=bucket, Key=key)
    return json.loads(response["Body"].read())


# ---------------------------------------------------------------------------
# EC2 metadata
# ---------------------------------------------------------------------------


def get_instance_id() -> str:
    """Fetch the current instance ID using IMDSv2."""
    try:
        token_req = urllib.request.Request(
            "http://169.254.169.254/latest/api/token",
            headers={"X-aws-ec2-metadata-token-ttl-seconds": "21600"},
            method="PUT",
        )
        token = urllib.request.urlopen(token_req, timeout=5).read().decode()

        id_req = urllib.request.Request(
            "http://169.254.169.254/latest/meta-data/instance-id",
            headers={"X-aws-ec2-metadata-token": token},
        )
        return urllib.request.urlopen(id_req, timeout=5).read().decode()
    except urllib.error.URLError as e:
        raise RuntimeError(f"failed to retrieve instance ID from IMDS: {e}") from e


# ---------------------------------------------------------------------------
# Shutdown
# ---------------------------------------------------------------------------


def shutdown(errors: list):
    """
    Handle end-of-run cleanup and process exit.

    In local mode exits immediately.
    In AWS mode self-terminates the EC2 instance before exiting.

    The LOCAL_MODE check is internal to this function.
    """
    if os.environ.get("LOCAL_MODE", "0") == "1":
        sys.exit(1 if errors else 0)

    import boto3

    region = os.environ.get("AWS_DEFAULT_REGION", "eu-west-2")

    try:
        instance_id = get_instance_id()
        log.info("terminating instance %s", instance_id)
        ec2 = boto3.client("ec2", region_name=region)
        ec2.terminate_instances(InstanceIds=[instance_id])
    except Exception as e:
        log.error("self-termination failed: %s", e)
        sys.exit(1)

    sys.exit(1 if errors else 0)


# ---------------------------------------------------------------------------
# Cache directory helpers
# ---------------------------------------------------------------------------


def model_to_cache_name(model_name: str) -> str:
    """HuggingFace convention: models--{org}--{repo}"""
    return "models--" + model_name.replace("/", "--")


def dir_size_gb(path: Path) -> float:
    """Recursively sum file sizes under path, return GB."""
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return total / (1024**3)


def cached_model_names(cache_path: Path) -> dict:
    """
    Scan the cache directory.
    Returns a mapping of model_name -> Path for all models on disk.
    """
    result = {}
    if not cache_path.exists():
        return result

    for entry in cache_path.iterdir():
        if not entry.is_dir():
            continue
        if not entry.name.startswith("models--"):
            continue
        remainder = entry.name[len("models--") :]
        parts = remainder.split("--")
        if len(parts) >= 2:
            model_name = "/".join(parts)
            result[model_name] = entry

    return result


def is_model_complete(cache_path: Path, model_name: str) -> bool:
    """
    A cached model is considered complete if its snapshots directory
    contains at least one entry.
    """
    cache_dir = cache_path / model_to_cache_name(model_name)
    snapshots = cache_dir / "snapshots"
    if not snapshots.exists():
        return False
    return any(snapshots.iterdir())


# ---------------------------------------------------------------------------
# Model caching
# ---------------------------------------------------------------------------


def cache_model(model: dict, cache_dir: str, hf_token: str, script: str) -> bool:
    """
    Invoke cache_model.py for a single model.
    Returns True on success.
    """
    if model.get("hf_token_required"):
        if not hf_token:
            log.warning(
                "%s requires an HF token but none is set -- skipping",
                model["name"],
            )
            return False

    env = os.environ.copy()
    env.update(
        {
            "MODELNAME": model["name"],
            "MODEL_TYPE": model["type"],
            "CACHE_DIR": cache_dir,
            "HF_HUB_CACHE": cache_dir,
            "HF_HUB_OFFLINE": "0",
            "HF_HUB_DISABLE_PROGRESS_BARS": "0",
            "LOCAL_FILES_ONLY": "0",
        }
    )

    if model["type"] in QUANTIZABLE_TYPES:
        env["LOAD_IN_4BIT"] = "0"

    if model.get("hf_token_required") and hf_token:
        env["HF_TOKEN"] = hf_token

    try:
        result = subprocess.run(
            ["python3", script],
            env=env,
            timeout=7200,
            check=False,
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        log.error("%s: timed out after 2 hours", model["name"])
        return False


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


@dataclass
class BuildResult:
    cached: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    pruned: list = field(default_factory=list)
    errors: list = field(default_factory=list)


def run_build(
    models: list, cache_path: Path, hf_token: str, script: str
) -> BuildResult:
    """
    Cache all declared models and prune any that are no longer declared.
    Always prunes -- the declared list is the source of truth.
    """
    result = BuildResult()
    existing = cached_model_names(cache_path)
    declared = {m["name"] for m in models}

    cache_path.mkdir(parents=True, exist_ok=True)

    for model in models:
        name = model["name"]

        if name in existing and is_model_complete(cache_path, name):
            log.info("skip %s (complete)", name)
            result.skipped.append(name)
            continue

        if name in existing:
            log.warning("%s: directory exists but appears incomplete, re-caching", name)

        log.info("caching %s", name)
        ok = cache_model(model, str(cache_path), hf_token, script)
        if ok:
            log.info("cached %s", name)
            result.cached.append(name)
        else:
            log.error("failed to cache %s", name)
            result.errors.append(name)

    for name, path in existing.items():
        if name not in declared:
            log.info("pruning %s", name)
            try:
                shutil.rmtree(path)
                log.info("pruned %s", name)
                result.pruned.append(name)
            except OSError as e:
                log.error("failed to prune %s: %s", name, e)
                result.errors.append(f"prune:{name}")

    return result


def print_build_summary(result: BuildResult, cache_path: Path):
    total_gb = sum(
        dir_size_gb(cache_path / model_to_cache_name(n))
        for n in list({*result.cached, *result.skipped})
        if (cache_path / model_to_cache_name(n)).exists()
    )

    print("\n--- build summary ---")
    for name in result.cached:
        gb = dir_size_gb(cache_path / model_to_cache_name(name))
        print(f"  cached:  {name} ({gb:.2f} GB)")
    for name in result.skipped:
        print(f"  skipped: {name} (complete)")
    for name in result.pruned:
        print(f"  pruned:  {name}")
    for name in result.errors:
        print(f"  error:   {name}")
    print(f"\n  total cache size: {total_gb:.2f} GB")
    if result.errors:
        print(f"  errors: {len(result.errors)}")
    print()


def run_inspect(models: list, cache_path: Path):
    """
    Report cache contents and drift from the declared model list.
    Exits non-zero if any declared model is missing or incomplete.
    """
    declared = {m["name"] for m in models}
    existing = cached_model_names(cache_path)
    anomalies = []

    print("\n--- cache inspection ---")
    print(f"  declared in config: {len(declared)}")
    print(f"  found on disk:      {len(existing)}\n")

    total_gb = 0.0

    for model in models:
        name = model["name"]
        path = cache_path / model_to_cache_name(name)
        complete = is_model_complete(cache_path, name)

        if name not in existing:
            status = "MISSING"
            gb = 0.0
            anomalies.append(name)
        elif not complete:
            status = "INCOMPLETE"
            gb = dir_size_gb(path)
            anomalies.append(name)
        else:
            status = "ok"
            gb = dir_size_gb(path)

        total_gb += gb
        print(f"  {status:<12} {name:<55} {gb:.2f} GB")

    undeclared = [n for n in existing if n not in declared]
    if undeclared:
        print()
        for name in undeclared:
            path = existing[name]
            gb = dir_size_gb(path)
            total_gb += gb
            print(f"  {'UNDECLARED':<12} {name:<55} {gb:.2f} GB")
            anomalies.append(name)

    print(f"\n  total cache size: {total_gb:.2f} GB")
    if anomalies:
        print(f"  anomalies: {len(anomalies)}")
    print()

    sys.exit(1 if anomalies else 0)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

SUBCOMMANDS = ("build", "inspect")


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in SUBCOMMANDS:
        print(f"usage: main.py [{' | '.join(SUBCOMMANDS)}]", file=sys.stderr)
        sys.exit(1)

    subcommand = sys.argv[1]
    cache_dir = os.environ.get("CACHE_DIR", "/mnt/efs/cache")
    hf_token = os.environ.get("HF_TOKEN", "")
    script = os.environ.get("CACHE_MODEL_SCRIPT", "/opt/cache_model.py")

    log.info(
        "cache manager: %s (local_mode=%s)",
        subcommand,
        os.environ.get("LOCAL_MODE", "0"),
    )
    log.info("cache_dir=%s", cache_dir)

    config = get_config()
    models = config.get("models", [])

    if not models:
        log.error("no models found in config")
        sys.exit(1)

    log.info("model list: %d models", len(models))

    cache_path = Path(cache_dir)

    if subcommand == "inspect":
        run_inspect(models, cache_path)

    if subcommand == "build":
        result = run_build(models, cache_path, hf_token, script)
        print_build_summary(result, cache_path)
        shutdown(result.errors)


if __name__ == "__main__":
    main()
