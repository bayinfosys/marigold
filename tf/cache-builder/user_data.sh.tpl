#!/bin/bash
# Cache builder startup script.
# Runs as root on Amazon Linux 2023.
#
# models_yaml_etag: ${models_yaml_etag}

set -euo pipefail

exec > >(tee /var/log/cache-builder.log) 2>&1
echo "cache builder starting: $(date -u +%Y-%m-%dT%H:%M:%SZ)"

# ---------------------------------------------------------------------------
# Install dependencies
# ---------------------------------------------------------------------------
dnf install -y amazon-efs-utils docker amazon-cloudwatch-agent
systemctl start docker

# ---------------------------------------------------------------------------
# Configure and start CloudWatch agent to stream the build log
# ---------------------------------------------------------------------------
INSTANCE_ID=$(curl -sf \
  -H "X-aws-ec2-metadata-token: $(curl -sf \
    -X PUT \
    -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' \
    http://169.254.169.254/latest/api/token)" \
  http://169.254.169.254/latest/meta-data/instance-id)

LOG_STREAM="$INSTANCE_ID/$(date -u +%Y%m%dT%H%M%SZ)"

cat > /opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json <<EOF
{
  "logs": {
    "logs_collected": {
      "files": {
        "collect_list": [
          {
            "file_path": "/var/log/cache-builder.log",
            "log_group_name": "${log_group}",
            "log_stream_name": "$LOG_STREAM",
            "retention_in_days": 30
          }
        ]
      }
    }
  }
}
EOF

/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \
  -a fetch-config \
  -m ec2 \
  -c file:/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json \
  -s

echo "cloudwatch agent started, streaming to ${log_group}/$LOG_STREAM"


# Hard deadline: terminate this instance after MAX_RUNTIME_SECONDS regardless
# of what is happening. Prevents indefinite hangs from stalled downloads.
MAX_RUNTIME_SECONDS=${max_runtime_seconds}
shutdown -h +$((MAX_RUNTIME_SECONDS / 60)) "cache builder deadline reached" &
SHUTDOWN_PID=$!

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
# Pull environment image from ECR
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
# Download models.yaml from S3
# The container image has a baked-in copy but it may be stale.
# The S3 copy is the authoritative version at deploy time.
# ---------------------------------------------------------------------------
echo "downloading models.yaml from s3://${assets_bucket}/${models_yaml_key}"
mkdir assets
aws s3 cp s3://${assets_bucket}/${models_yaml_key} assets/models.yaml

# ---------------------------------------------------------------------------
# Run the cache builder -- download weights to EFS
# The container writes to /mnt/efs which is the EFS mount.
# AWS operations (S3 write, self-termination) happen on the host after
# the container exits, where the EC2 instance role credentials are available.
# ---------------------------------------------------------------------------
echo "starting cache download"

DOWNLOAD_CID=$(docker run -d \
  -e MODELS_YAML_PATH=/app/assets/models.yaml \
  -e CACHE_DIR=/mnt/efs \
  -e HF_HUB_CACHE=/mnt/efs \
  -e HF_HUB_OFFLINE=0 \
  -e HF_TOKEN="$HF_TOKEN" \
  -v /mnt/efs:/mnt/efs \
  -v $(pwd)/assets:/app/assets:ro \
  ${model_cache_image_uri} \
  python3 -m tools.model_cli download-weights)

echo "download container started: $DOWNLOAD_CID"
docker logs -f "$DOWNLOAD_CID"
DOWNLOAD_EXIT=$(docker wait "$DOWNLOAD_CID")
docker rm "$DOWNLOAD_CID"
echo "cache download finished with exit code $DOWNLOAD_EXIT"

# ---------------------------------------------------------------------------
# Write cache state to S3 -- runs on the host where IAM credentials work
# ---------------------------------------------------------------------------
echo "running cache inspection"

INSPECT_CID=$(docker run -d \
  -e MODELS_YAML_PATH=/app/assets/models.yaml \
  -e CACHE_DIR=/mnt/efs \
  -e HF_HUB_CACHE=/mnt/efs \
  -e HF_HUB_OFFLINE=1 \
  -v /mnt/efs:/mnt/efs \
  -v $(pwd)/assets:/app/assets:ro \
  ${model_cache_image_uri} \
  python3 -m tools.model_cli --json inspect-cache)

echo "inspect container started: $INSPECT_CID"
docker logs -f "$INSPECT_CID" > /tmp/cache_state.json 2>/var/log/cache-inspect-stderr.log
INSPECT_EXIT=$(docker wait "$INSPECT_CID")
docker rm "$INSPECT_CID"
echo "cache inspection finished with exit code $INSPECT_EXIT"

echo "uploading cache state to s3://${assets_bucket}/cache_state.json"
aws s3 cp /tmp/cache_state.json s3://${assets_bucket}/cache_state.json

# ---------------------------------------------------------------------------
# Upload build log to S3 for post-mortem access after instance terminates
# ---------------------------------------------------------------------------
echo "uploading build log to s3://${assets_bucket}/cache-builder-logs/$(date -u +%Y%m%dT%H%M%SZ).log"
aws s3 cp /var/log/cache-builder.log \
  s3://${assets_bucket}/cache-builder-logs/$(date -u +%Y%m%dT%H%M%SZ).log

# Cancel the deadline shutdown since we completed normally.
kill $SHUTDOWN_PID 2>/dev/null || true

# ---------------------------------------------------------------------------
# Self-terminate
# The instance role has ec2:TerminateInstances scoped to instances tagged
# with this instance's Name tag.
# ---------------------------------------------------------------------------
INSTANCE_ID=$(curl -sf \
  -H "X-aws-ec2-metadata-token: $(curl -sf \
    -X PUT \
    -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' \
    http://169.254.169.254/latest/api/token)" \
  http://169.254.169.254/latest/meta-data/instance-id)

echo "terminating instance $INSTANCE_ID"
aws ec2 terminate-instances \
  --instance-ids "$INSTANCE_ID" \
  --region ${region}

echo "termination requested"
