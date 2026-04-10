"""Cache builder -- AWS mode.

Reads model configuration from S3 and self-terminates the EC2 instance
on completion. Intended to run as a one-shot EC2 instance launched by
Terraform (tf/cache-builder).

Usage:
  python3 cache_builder_aws.py build
  python3 cache_builder_aws.py inspect

Environment variables:
  MODELS_S3_BUCKET      S3 bucket containing models.json (required)
  MODELS_S3_KEY         S3 key for models.json (required)
  CACHE_DIR             Path for model cache (default: /mnt/efs/cache)
  HF_TOKEN              HuggingFace token for gated models
  AWS_DEFAULT_REGION    AWS region (default: eu-west-2)
  LOG_LEVEL             Python logging level (default: INFO)
"""

import json
import logging
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from .model_cache_shared import (
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
    import boto3

    region = os.environ.get("AWS_DEFAULT_REGION", "eu-west-2")
    bucket = os.environ["MODELS_S3_BUCKET"]
    key = os.environ["MODELS_S3_KEY"]

    log.info("fetching s3://%s/%s", bucket, key)
    s3 = boto3.client("s3", region_name=region)
    response = s3.get_object(Bucket=bucket, Key=key)
    return json.loads(response["Body"].read())


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
        raise RuntimeError("failed to retrieve instance ID from IMDS: %s" % e) from e


def shutdown(errors: list):
    """Self-terminate the EC2 instance, then exit."""
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


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in SUBCOMMANDS:
        print("usage: cache_builder_aws.py [%s]" % " | ".join(SUBCOMMANDS), file=sys.stderr)
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
        shutdown(anomalies)

    if subcommand == "build":
        result = run_build(models, cache_path, hf_token)
        print_build_summary(result, cache_path)
        shutdown(result.errors)


if __name__ == "__main__":
    main()
