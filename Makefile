PROJECT_NAME=marigold

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
	# the environment container provides everything for running marigold
	docker build \
	  --build-arg GIT_TAG=$(TAG) \
	  -t $(PROJECT_NAME)/environment:$(TAG) \
	  -f package/src/models/environment/Dockerfile.ecs .

	# the gpu environment container provides everything for running marigold on nvidia gpus
	# --build-arg BASE_IMAGE=nvidia/cuda:13.1.2-cudnn-runtime-ubuntu24.04 \
	docker build \
	  --build-arg BASE_IMAGE=nvidia/cuda:13.0.0-cudnn-runtime-ubuntu24.04 \
	  -t $(PROJECT_NAME)/cuda-python312:$(TAG) \
	  -f package/src/models/environment/Dockerfile.python312.gpu .

	docker build \
	  --build-arg BASE_IMAGE=$(PROJECT_NAME)/cuda-python312:$(TAG) \
	  --build-arg GPU_ENABLED=1 \
	  --build-arg GIT_TAG=$(TAG) \
	  --build-arg TORCH_REQS=pytorch-gpu.requirements.txt \
	  -t $(PROJECT_NAME)/environment:$(TAG)-gpu \
	  -f package/src/models/environment/Dockerfile.ecs .

	docker build \
	  --build-arg BASE_IMAGE=$(PROJECT_NAME)/environment:$(TAG) \
	  --build-arg GIT_TAG=$(TAG) \
	  -t $(PROJECT_NAME)/worker:$(TAG) \
	  -f package/src/models/environment/Dockerfile.worker .

	docker build \
	  --build-arg BASE_IMAGE=$(PROJECT_NAME)/environment:$(TAG)-gpu \
	  --build-arg GPU_ENABLED=1 \
	  --build-arg GIT_TAG=$(TAG) \
	  -t $(PROJECT_NAME)/worker:$(TAG)-gpu \
	  -f package/src/models/environment/Dockerfile.worker .

# ---------------------------------------------------------------------------
# Tools
#
# This only contains the magika model, which we don't really use at the moment
# ---------------------------------------------------------------------------

build/tools/%:
	docker build \
	  --build-arg GIT_TAG=$(TAG) \
	  -t $(PROJECT_NAME)/tools/$*:$(TAG) \
	  -f package/src/tools/$*/Dockerfile .

.PHONY: build build/tools push push/tools
build: build/environment build/tools


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

LOCAL_CACHE_DIR = /data/marigold/model-cache/
LOCAL_OUTPUT_DIR = /data/marigold/model-outputs/
#MODELS_YAML ?= assets/models-2060.yaml
MODELS_YAML ?= assets/models-3060.yaml

.PHONY: cli/download-weights
cli/download-weights:
	docker run --rm \
	  -e MODELS_YAML_PATH=/app/assets/models.yaml \
	  -e CACHE_DIR=/models \
	  -e HF_HUB_OFFLINE=0 \
	  -e HF_HUB_CACHE=/models \
	  -e HF_TOKEN=$(HF_TOKEN) \
	  -e MODEL_NAME=test \
	  -e MODEL_HASH=test \
	  -e MODEL_TYPE=test \
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
# API definition
# ---------------------------------------------------------------------------

.PHONY: build/api-definition
build/api-definition:
	docker run -it --rm \
	  -v $(shell pwd)/package/src/:/app:ro \
	  -v $(shell pwd)/tf/03/rest:/out \
	  -e CORS_ORIGINS="*" \
	  -e CORS_HEADERS="Content-Type,Authorization,Origin,x-api-key" \
	  bayis/fastapi_aws:v0.0.11-1-ga17b8a1 \
	    --title mdl \
	    --router api.routes:router \
	    --out-public /out/api_public_definition.json \
	    --out-private /out/api_private_definition.json \
	    --version $(TAG)

.PHONY: build/deployment-artefacts
build/deployment-artefacts: build/api-definition

# ---------------------------------------------------------------------------
# Python environment
# ---------------------------------------------------------------------------

PYTHON       := .venv/bin/python3
PYTHONPATH   := package/src
GENERATE     := PYTHONPATH=$(PYTHONPATH) $(PYTHON) package/src/tools/generate_models_tfvars.py

.venv:
	virtualenv -p python3 .venv
	.venv/bin/pip install --quiet pyyaml pydantic requests numpy boto3

# ---------------------------------------------------------------------------
# Model and tools asset pipeline
#
# Typical workflow after editing models.yaml or tools.yaml:
#
#   make models/validate
#   make assets/generate
#   git add assets/
#   LAYER=02 make plan && LAYER=02 make apply
#   make deploy/cache-builder
# ---------------------------------------------------------------------------

.PHONY: models/validate
models/validate: .venv assets/models.yaml
	$(GENERATE) assets/models.yaml validate

.PHONY: assets/generate
assets/generate: .venv assets/models.yaml assets/tools.yaml
	$(GENERATE) assets/models.yaml terraform-data > assets/models.tfvars
	$(GENERATE) assets/models.yaml infra-data   > assets/models.json
	$(GENERATE) assets/models-2060.yaml infra-data > assets/models-2060.json
	$(GENERATE) assets/models-3060.yaml infra-data > assets/models-3060.json
	$(GENERATE) assets/models.yaml jekyll-data > assets/jekyll-models.json
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) package/src/tools/generate_tools_index.py \
	  assets/tools.yaml \
	  assets/cache_state.json

.PHONY: assets/catalogue
assets/merge-hf-data: .venv assets/models.yaml
	HF_TOKEN=$(HF_TOKEN) $(GENERATE) assets/models.yaml public > assets/public_models_reference.json
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) package/src/tools/model_cli.py build-catalogue \
	  assets/public_models_reference.json \
	  --cache-state assets/cache_state.json
