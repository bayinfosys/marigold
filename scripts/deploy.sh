#!/bin/bash
set -euo pipefail

#
# Prerequisites:
#   - AWS credentials configured
#   - git tag present (used as ECR image tag)
#   - TF_VAR_hf_token set if any gated models are in assets/models.yaml
#

# Generate Terraform variable files from models.yaml.
# Pure transformation, no network required.
make models/validate
make assets/generate

# layer 01: VPC, EFS, ECR
LAYER=01 make init
LAYER=01 make plan
LAYER=01 make apply

# build and push the environment container image
make build/environment
make docker-login
make push/environment

# layer 02: ECS, SQS, lambdas, DynamoDB, S3
LAYER=02 make init
LAYER=02 make plan
LAYER=02 make apply

# build API definition (reads from package source, writes to tf/03/rest)
make build/api-definition

# layer 03: API Gateway, domains, certs
LAYER=03 make init
LAYER=03 make plan
LAYER=03 make apply

echo ""
echo "Infrastructure deployed."
echo "To populate the model cache:  make cache/build"
echo "After cache builder completes: make assets/generate"

# populate EFS model cache
# TF_VAR_hf_token must be set in the environment for gated models
make deploy/cache-builder
