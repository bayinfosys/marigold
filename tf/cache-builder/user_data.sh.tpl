#!/bin/bash
# Cache builder startup script.
# Runs as root on Amazon Linux 2023.
# Pulls the model-cache container from ECR, mounts EFS, runs the cache manager.
#
# models_json_etag: ${models_json_etag}
# (included so user_data changes when models.json changes, forcing instance replacement)

set -euo pipefail

exec > >(tee /var/log/cache-builder.log) 2>&1
echo "cache builder starting: $(date -u +%Y-%m-%dT%H:%M:%SZ)"

# ---------------------------------------------------------------------------
# Install dependencies
# ---------------------------------------------------------------------------
dnf install -y amazon-efs-utils docker
systemctl start docker

# ---------------------------------------------------------------------------
# Mount EFS with the read-write access point
# ---------------------------------------------------------------------------
mkdir -p /mnt/efs
mount -t efs \
  -o tls,iam,accesspoint=${efs_access_point_id} \
  ${efs_file_system_id}: \
  /mnt/efs

echo "efs mounted"

# ---------------------------------------------------------------------------
# Pull model-cache image from ECR
# ---------------------------------------------------------------------------
aws ecr get-login-password --region ${region} | \
  docker login \
    --username AWS \
    --password-stdin \
    ${ecr_registry}

docker pull ${model_cache_image_uri}
echo "image pulled"

# ---------------------------------------------------------------------------
# Read HuggingFace token from SSM
# ---------------------------------------------------------------------------
HF_TOKEN=$(aws ssm get-parameter \
  --name "${ssm_hf_token_name}" \
  --with-decryption \
  --query Parameter.Value \
  --output text \
  --region ${region}) || HF_TOKEN=""

if [ -z "$HF_TOKEN" ] || [ "$HF_TOKEN" = "not-set" ]; then
  echo "hf_token not set -- gated models will be skipped"
  HF_TOKEN=""
fi

# ---------------------------------------------------------------------------
# Run the cache manager
# Self-termination of this EC2 instance is handled inside the container.
# ---------------------------------------------------------------------------
echo "starting cache manager"

docker run --rm \
  -e MODELS_S3_BUCKET="${assets_bucket}" \
  -e MODELS_S3_KEY="${models_json_key}" \
  -e CACHE_DIR="/mnt/efs/cache" \
  -e HF_HUB_CACHE="/mnt/efs/cache" \
  -e HF_TOKEN="$HF_TOKEN" \
  -e AWS_DEFAULT_REGION="${region}" \
  -v /mnt/efs:/mnt/efs \
  ${model_cache_image_uri} \
  build
