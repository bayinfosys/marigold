"""Cache builder -- local mode.

Reads model configuration from a YAML file on the local filesystem.
Use this during development to populate a local model cache without
deploying to AWS.

Usage:
  MODELS_YAML_PATH=assets/models.yaml python3 cache_builder_local.py build
  MODELS_YAML_PATH=assets/models.yaml python3 cache_builder_local.py inspect

Environment variables:
  MODELS_YAML_PATH    Path to models.yaml (required)
  CACHE_DIR           Path for model cache (default: /mnt/efs/cache)
  HF_TOKEN            HuggingFace token for gated models
  LOG_LEVEL           Python logging level (default: INFO)
"""

import logging
import os
import sys
from pathlib import Path

from cache_builder_shared import (
    print_build_summary,
    run_build,
    run_inspect,
)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("cache-manager")

SUBCOMMANDS = ("build", "inspect")


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

    log.info("reading %s", yaml_path)
    with open(yaml_path) as fh:
        return yaml.safe_load(fh)


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in SUBCOMMANDS:
        print("usage: cache_builder_local.py [%s]" % " | ".join(SUBCOMMANDS), file=sys.stderr)
        sys.exit(1)

    subcommand = sys.argv[1]
    cache_dir = os.environ.get("CACHE_DIR", "/mnt/efs/cache")
    hf_token = os.environ.get("HF_TOKEN", "")

    log.info("subcommand=%s cache_dir=%s", subcommand, cache_dir)

    config = get_config()
    models = config.get("models", [])

    if not models:
        log.error("no models found in config")
        sys.exit(1)

    log.info("model list: %d models", len(models))

    cache_path = Path(cache_dir)

    if subcommand == "inspect":
        anomalies = run_inspect(models, cache_path)
        sys.exit(1 if anomalies else 0)

    if subcommand == "build":
        result = run_build(models, cache_path, hf_token)
        print_build_summary(result, cache_path)
        sys.exit(1 if result.errors else 0)


if __name__ == "__main__":
    main()
