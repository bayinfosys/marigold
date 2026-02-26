#PROJECT_NAME=vecmdl

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

# ---------------------------------------------------------------------------
# Container image
# ---------------------------------------------------------------------------

.PHONY: build/environment
build/environment:
	docker build \
	  -t $(PROJECT_NAME)/environment:$(TAG) \
	  -f package/src/models/environment/Dockerfile.ecs .

build/model-cache: build/environment
	docker build \
	  --build-arg BASE_IMAGE=$(PROJECT_NAME)/environment:$(TAG) \
	  -t $(PROJECT_NAME)/model-cache:$(TAG) \
	  -f package/src/tools/model-cache/Dockerfile .

push/environment:
	docker tag $(PROJECT_NAME)/environment:$(TAG) $(AWS_ACCOUNT_ID).dkr.ecr.$(AWS_REGION).amazonaws.com/bayis/$(PROJECT_NAME)/environment:$(TAG) && \
	docker push $(AWS_ACCOUNT_ID).dkr.ecr.$(AWS_REGION).amazonaws.com/bayis/$(PROJECT_NAME)/environment:$(TAG) && \
	docker rmi $(AWS_ACCOUNT_ID).dkr.ecr.$(AWS_REGION).amazonaws.com/bayis/$(PROJECT_NAME)/environment:$(TAG)

.PHONY: build/lame
build/lame:
	# build the lame executable for aws lambda
	# output goes to ./tf/02/lambdas/lame
	docker run \
	  --rm \
	  -it \
	  -v ./scripts:/scripts:ro \
	  -v ./tf/02/lambdas/lame:/var/task/lame/bin \
	  amazonlinux:2 \
	  bash -c '/scripts/build-lame.sh'

# ---------------------------------------------------------------------------
# Tools
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
# Local model cache
#
# Cache all models declared in assets/models.yaml:
#   make cache/local
#
# To cache a subset, create assets/models-dev.yaml and run:
#   make MODELS_YAML=assets/models-dev.yaml cache/local
#
# Inspect cache contents and drift from models.yaml:
#   make cache/inspect
# ---------------------------------------------------------------------------

MODELS_YAML ?= assets/models.yaml

CACHE_LOCAL_RUN = \
	docker run \
	  --rm \
	  -e LOCAL_MODE=1 \
	  -e MODELS_YAML_PATH=/project/assets/models.yaml \
	  -e CACHE_DIR=/models \
	  -e HF_HUB_CACHE=/models \
	  -e HF_TOKEN=$(HF_TOKEN) \
	  -v $(shell pwd)/$(MODELS_YAML):/project/assets/models.yaml:ro \
	  -v $(shell pwd)/cache/models:/models \
	  $(PROJECT_NAME)/model-cache:$(TAG)

.PHONY: cache/local
cache/local: build/model-cache
	$(CACHE_LOCAL_RUN) build

.PHONY: cache/inspect
cache/inspect: build/model-cache
	$(CACHE_LOCAL_RUN) inspect

# ---------------------------------------------------------------------------
# Docker utilities
# ---------------------------------------------------------------------------

docker-login:
	@echo "Logging into Amazon ECR..."
	aws ecr get-login-password --region $(AWS_REGION) | \
	docker login --username AWS --password-stdin \
	  $(AWS_ACCOUNT_ID).dkr.ecr.$(AWS_REGION).amazonaws.com

run:
	GIT_TAG=$(shell git describe --tags) \
	docker compose up --abort-on-container-exit --remove-orphans

stop:
	docker compose stop
	docker compose rm

# ---------------------------------------------------------------------------
# API definition
# ---------------------------------------------------------------------------

.PHONY: build/api-definition
build/api-definition:
	docker run -it --rm \
	  -v $(shell pwd)/package/src/api:/app/routes:ro \
	  -v $(shell pwd)/tf/03/rest:/out \
	  bayis/fastapi_aws:v0.0.11-1-ga17b8a1 \
	    --title mdl \
	    --router routes.routes:router \
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
	.venv/bin/python3 scripts/generate_models_tfvars.py \
	  assets/models.yaml validate

.PHONY: models/generate
models/generate: .venv assets/models.yaml
	.venv/bin/python3 scripts/generate_models_tfvars.py \
	  assets/models.yaml tfvars > assets/models.tfvars
	.venv/bin/python3 scripts/generate_models_tfvars.py \
	  assets/models.yaml json > assets/models.json

.PHONY: models/catalogue
models/catalogue: .venv assets/models.yaml
	HF_TOKEN=$(HF_TOKEN) \
	.venv/bin/python3 scripts/generate_models_tfvars.py \
	  assets/models.yaml public > assets/public_models_reference.json

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

plan: generate-models validate
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

TF_EXTRA_VARS ?=

.PHONY: deploy/cache-builder
deploy/cache-builder:
	terraform -chdir=tf/tools/cache-builder init -upgrade -reconfigure
	terraform -chdir=tf/tools/cache-builder plan \
	  -var-file=../../common.tfvars \
	  -var-file=../../$(ENV).tfvars \
	  -var="git_tag=$(TAG)" \
	  $(TF_EXTRA_VARS) \
	  -out new.plan
	terraform -chdir=tf/tools/cache-builder apply -parallelism=0 new.plan \
	  && rm tf/tools/cache-builder/new.plan

# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

get-key:
	terraform -chdir=tf/03 output -raw api_key_value

get-asset-bucket:
	terraform -chdir=tf/02 output -raw asset_bucket_name

get-api-spec:
	terraform -chdir=tf/03 output -raw api_spec

get-cache-builder-instance:
	terraform -chdir=tf/tools/cache-builder output -raw cache_builder_instance_id
