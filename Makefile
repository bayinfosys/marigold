PROJECT_NAME=vecmdl

AWS_ACCOUNT_ID=789643290641
AWS_REGION=eu-west-2

# HF_TOKEN is read from the shell environment.
# Export it before running any target that requires gated models:
#   export HF_TOKEN=hf_xxxx
HF_TOKEN ?=

# TAG is derived from the current git tag.
# Override on the command line: make TAG=v0.3.0 plan
TAG ?= $(shell git describe --tags)

ifeq ($(TAG),)
  $(error TAG is not set -- ensure a git tag exists or pass TAG= explicitly)
endif

ENV ?= dev
MODELS_YAML ?= assets/models.yaml

# ---------------------------------------------------------------------------
# Container image
# ---------------------------------------------------------------------------

.PHONY: build/environment
build/environment:
	# the environment container provides everything for running marigold
	docker build \
	  -t $(PROJECT_NAME)/environment:$(TAG) \
	  -f package/src/models/environment/Dockerfile.ecs .

push/environment:
	docker tag $(PROJECT_NAME)/environment:$(TAG) $(AWS_ACCOUNT_ID).dkr.ecr.$(AWS_REGION).amazonaws.com/bayis/$(PROJECT_NAME)/environment:$(TAG) && \
	docker push $(AWS_ACCOUNT_ID).dkr.ecr.$(AWS_REGION).amazonaws.com/bayis/$(PROJECT_NAME)/environment:$(TAG) && \
	docker rmi $(AWS_ACCOUNT_ID).dkr.ecr.$(AWS_REGION).amazonaws.com/bayis/$(PROJECT_NAME)/environment:$(TAG)

# ---------------------------------------------------------------------------
# Tools
#
# This only contains the magika model, which we don't really use at the moment
# ---------------------------------------------------------------------------

build/tools/%:
	docker build \
	  -t $(PROJECT_NAME)/tools/$*:$(TAG) \
	  -f package/src/tools/$*/Dockerfile .

push/tools/%:
	docker tag $(PROJECT_NAME)/tools/$*:$(TAG) $(AWS_ACCOUNT_ID).dkr.ecr.$(AWS_REGION).amazonaws.com/bayis/$(PROJECT_NAME)/tools/$*:$(TAG) && \
	docker push $(AWS_ACCOUNT_ID).dkr.ecr.$(AWS_REGION).amazonaws.com/bayis/$(PROJECT_NAME)/tools/$*:$(TAG) && \
	docker rmi $(AWS_ACCOUNT_ID).dkr.ecr.$(AWS_REGION).amazonaws.com/bayis/$(PROJECT_NAME)/tools/$*:$(TAG)

.PHONY: build build/tools push push/tools
build: build/environment build/tools
push: push/environment push/tools


# ---------------------------------------------------------------------------
# Local model development
#
# Download model weights:
#   make cli/download-weights
#   make cli/download-weights ARGS=stable-diffusion-v1-5
#
# Inspect cache state:
#   make cli/inspect-cache
#   make cli/inspect-cache FLAGS=--json
#
# Test all models:
#   make cli/test-models
#   make cli/test-models ARGS=stable-diffusion-v1-5
#
# Run a single inference:
#   make cli/run-model ARGS="stable-diffusion-v1-5 txt2img --request -"
#
# Build public catalogue:
#   make cli/build-catalogue ARGS="assets/public_models_reference.json --cache-state /tmp/cache_state.json"
#
# Run a workflow locally:
#   make cli/workflow/run ARGS="path/to/workflow.yaml --input text=hello"
#   make cli/workflow/test ARGS=/workflows/
# ---------------------------------------------------------------------------

LOCAL_CACHE_DIR = $(shell pwd)/cache/models
LOCAL_OUTPUT_DIR = $(shell pwd)/cache/outputs

.PHONY: cli/download-weights
cli/download-weights:
	docker run --rm \
	  -e MODELS_YAML_PATH=/app/assets/models.yaml \
	  -e CACHE_DIR=/models \
	  -e HF_HUB_OFFLINE=0 \
	  -e HF_HUB_CACHE=/models \
	  -e HF_TOKEN=$(HF_TOKEN) \
	  -v $(shell pwd)/$(MODELS_YAML):/app/assets/models.yaml:ro \
	  -v $(LOCAL_CACHE_DIR):/models \
	  $(PROJECT_NAME)/environment:$(TAG) \
	  python3 -m tools.model_cli download-weights $(ARGS)

cli/%:
	docker run --rm -i \
	  -e MODELS_YAML_PATH=/app/assets/models.yaml \
	  -e CACHE_DIR=/models \
	  -e HF_HUB_CACHE=/models \
	  -e HF_HUB_OFFLINE=1 \
	  -e OUTPUT_DIR=/outputs \
	  -v $(shell pwd)/$(MODELS_YAML):/app/assets/models.yaml:ro \
	  -v $(shell pwd)/test-workflows:/workflows:ro \
	  -v $(LOCAL_CACHE_DIR):/models:ro \
	  -v $(LOCAL_OUTPUT_DIR):/outputs \
	  $(PROJECT_NAME)/environment:$(TAG) \
	  python3 -m tools.model_cli $(FLAGS) $* $(ARGS)


.PHONY: cli/workflow/run cli/workflow/test
cli/workflow/run:
	docker run --rm -i \
	  -e MODELS_YAML_PATH=/app/assets/models.yaml \
	  -e CACHE_DIR=/models \
	  -e HF_HUB_CACHE=/models \
	  -e HF_HUB_OFFLINE=1 \
	  -v $(shell pwd)/$(MODELS_YAML):/app/assets/models.yaml:ro \
	  -v $(shell pwd)/test-workflows:/workflows:ro \
	  -v $(LOCAL_CACHE_DIR):/models:ro \
	  $(PROJECT_NAME)/environment:$(TAG) \
	  python3 -m tools.model_cli $(FLAGS) workflow run $(ARGS)

cli/workflow/test:
	docker run --rm \
	  -e MODELS_YAML_PATH=/app/assets/models.yaml \
	  -e CACHE_DIR=/models \
	  -e HF_HUB_CACHE=/models \
	  -e HF_HUB_OFFLINE=1 \
	  -v $(shell pwd)/$(MODELS_YAML):/app/assets/models.yaml:ro \
	  -v $(shell pwd)/test-workflows:/workflows:ro \
	  -v $(LOCAL_CACHE_DIR):/models:ro \
	  $(PROJECT_NAME)/environment:$(TAG) \
	  python3 -m tools.model_cli $(FLAGS) workflow test $(ARGS)



# ---------------------------------------------------------------------------
# Local integration testing
#
# Starts LocalStack (S3, DynamoDB, SQS) and the model container.
#   make integration/up
#   make integration/exec ARGS="test sentence-transformers/all-minilm-l6-v2"
#   make integration/exec ARGS="workflow run tools/test-workflows/embed_text.yaml --input text=hello"
#   make integration/down
# ---------------------------------------------------------------------------

.PHONY: integration/up
integration/up:
	TAG=$(TAG) docker compose -f docker-compose.integration.yaml up -d

.PHONY: integration/down
integration/down:
	TAG=$(TAG) docker compose -f docker-compose.integration.yaml down -v
	TAG=$(TAG) docker compose -f docker-compose.integration.yaml stop
	TAG=$(TAG) docker compose -f docker-compose.integration.yaml rm

.PHONY: integration/exec
integration/exec:
	TAG=$(TAG) docker compose -f docker-compose.integration.yaml exec marigold \
	  python3 -m tools.model_cli $(ARGS)


# ---------------------------------------------------------------------------
# Docker utilities
# ---------------------------------------------------------------------------

docker-login:
	@echo "Logging into Amazon ECR..."
	aws ecr get-login-password --region $(AWS_REGION) | \
	docker login --username AWS --password-stdin \
	  $(AWS_ACCOUNT_ID).dkr.ecr.$(AWS_REGION).amazonaws.com

# ---------------------------------------------------------------------------
# API definition
# ---------------------------------------------------------------------------

.PHONY: build/api-definition
build/api-definition:
	docker run -it --rm \
	  -v $(shell pwd)/package/src/:/app:ro \
	  -v $(shell pwd)/tf/03/rest:/out \
	  bayis/fastapi_aws:v0.0.11-1-ga17b8a1 \
	    --title mdl \
	    --router api.routes:router \
	    --out-public /out/api_public_definition.json \
	    --out-private /out/api_private_definition.json \
	    --version $(TAG)

.PHONY: build/deployment-artefacts
build/deployment-artefacts: build/api-definition

# ---------------------------------------------------------------------------
# Model definitions
#
# validate-models     validate models.yaml schema -- no output files
# generate-models     write models.tfvars and models.json (no network needed)
# generate-catalogue  write public_models_reference.json (fetches provider APIs)
#
# Typical workflow after editing models.yaml:
#   make validate-models
#   make generate-models
#   make generate-catalogue   # set HF_TOKEN if any auth_required: true entries
#   git add assets/models.yaml \
#           assets/models.tfvars \
#           assets/models.json \
#           assets/public_models_reference.json
#   LAYER=02 make plan && LAYER=02 make apply
#   make deploy/cache-builder
#
# Layer 03 no longer needs a separate apply step for the model catalogue.
# ---------------------------------------------------------------------------

.venv:
	virtualenv -p python3 .venv
	.venv/bin/pip install --quiet pyyaml pydantic requests

.PHONY: models/validate
models/validate: .venv assets/models.yaml
	# check the models.yaml is a valid file
	cd package/src && ../../.venv/bin/python3 tools/generate_models_tfvars.py \
	  assets/models.yaml validate

.PHONY: models/generate
models/generate: .venv assets/models.yaml
	# generate the terraform files from the model spec in `models.yaml`
	PYTHONPATH=package/src .venv/bin/python3 package/src/tools/generate_models_tfvars.py \
	  assets/models.yaml tfvars > assets/models.tfvars
	PYTHONPATH=package/src .venv/bin/python3 package/src/tools/generate_models_tfvars.py \
	  assets/models.yaml json > assets/models.json

.PHONY: models/catalogue
models/catalogue: .venv assets/models.yaml
	HF_TOKEN=$(HF_TOKEN) \
	.venv/bin/python3 package/src/tools/generate_models_tfvars.py \
	  assets/models.yaml public > assets/public_models_reference.json


.PHONY: generate-public-models
models/generate-public-models:
	# Download current cache state from S3
	aws s3 cp s3://bayis-vecmdl-dev-assets20241025234947605200000001/cache_state.json assets/cache_state.json --region eu-west-2
	# Merge public catalogue with cache state and upload
	PYTHONPATH=package/src .venv/bin/python3 package/src/tools/generate_models_tfvars.py assets/models.yaml public > assets/public_models_reference.json
	PYTHONPATH=package/src .venv/bin/python3 package/src/tools/model_cli.py build-catalogue \
	  assets/public_models_reference.json \
	  --cache-state assets/cache_state.json


# ---------------------------------------------------------------------------
# Terraform
#
# Layers 01, 02, and 03
#   LAYER=01 make init
#   LAYER=01 make plan
#   LAYER=01 make apply
#
# The cache builder is a separate tool layer with its own target:
#   make deploy/cache-builder
#   (set TF_VAR_hf_token in the environment before running if gated models
#   are present in assets/models.yaml)
# ---------------------------------------------------------------------------

.ONESHELL:

check-layer:
	@if [ -z "$(LAYER)" ]; then \
	  echo "error: LAYER is not set"; \
	  exit 1; \
	fi

init: check-layer
	terraform -chdir=tf/$(LAYER) init -upgrade -reconfigure

validate: check-layer
	terraform -chdir=tf/$(LAYER) validate

plan: # models/generate validate
	terraform -chdir=tf/$(LAYER) plan \
	  -var-file=../common.tfvars \
	  -var-file=../$(ENV).tfvars \
	  -var-file=../../assets/models.tfvars \
	  -var="git_tag=$(TAG)" \
	  -out new.plan

apply: check-layer
	terraform -chdir=tf/$(LAYER) apply -parallelism=0 new.plan \
	  && rm tf/$(LAYER)/new.plan

destroy: check-layer
	terraform -chdir=tf/$(LAYER) destroy \
	  -var-file=../common.tfvars \
	  -var-file=../$(ENV).tfvars \
	  -var="git_tag=$(TAG)" \
	  -auto-approve

status: check-layer
	terraform -chdir=tf/$(LAYER) state list

# ---------------------------------------------------------------------------
# Cache builder deployment
#
# Applies tf/tools/cache-builder, which starts an EC2 instance that
# populates EFS with model weights declared in assets/models.yaml.
#
# The instance self-terminates when the cache run is complete.
# Monitor progress via SSM Session Manager or CloudWatch Logs:
#   aws ssm start-session --target $(make get-cache-builder-instance)
#
# For gated models (hf_token_required: true in models.yaml):
#   export TF_VAR_hf_token=hf_xxxx
#
# To prune models removed from models.yaml:
#   make deploy/cache-builder TF_EXTRA_VARS='-var="prune_cache=true"'
# ---------------------------------------------------------------------------

MY_IP := $(shell curl -sf https://checkip.amazonaws.com)/32


TF_EXTRA_VARS ?=

.PHONY: deploy/cache-builder
deploy/cache-builder:
	terraform -chdir=tf/cache-builder init -upgrade -reconfigure
	terraform -chdir=tf/cache-builder plan \
	  -var-file=../common.tfvars \
	  -var-file=../$(ENV).tfvars \
	  -var="git_tag=$(TAG)" \
	  -var="ssh_allowed_cidr=$(MY_IP)" \
	  $(TF_EXTRA_VARS) \
	  -out new.plan
	terraform -chdir=tf/cache-builder apply -parallelism=0 new.plan \
	  && rm tf/cache-builder/new.plan

# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

get-api-key:
	terraform -chdir=tf/03 output -raw master_api_key_value

get-asset-bucket:
	terraform -chdir=tf/02 output -raw asset_bucket_name

get-api-spec:
	terraform -chdir=tf/03 output -raw api_spec

get-cache-builder-instance:
	terraform -chdir=tf/cache-builder output -raw cache_builder_instance_id
