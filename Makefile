PROJECT_NAME=marigold

# HF_TOKEN is read from the shell environment.
# Export it before running any target that requires gated models:
#   export HF_TOKEN=hf_xxxx
HF_TOKEN ?=

# TAG is derived from the current git tag.
# Override on the command line: make TAG=v0.3.0 plan
#TAG ?= $(shell git describe --tags)
TAG ?= $(shell python3 -m setuptools_scm)

ifeq ($(TAG),)
  $(error TAG is not set -- ensure a git tag exists or pass TAG= explicitly)
endif


ENV ?= dev

# ---------------------------------------------------------------------------
# Container images
# ---------------------------------------------------------------------------

GHCR_NAMESPACE ?= ghcr.io/bayinfosys
API_IMAGE      ?= $(GHCR_NAMESPACE)/marigold-api
CACHE_IMAGE    ?= $(GHCR_NAMESPACE)/marigold-cache
WORKER_IMAGE   ?= $(GHCR_NAMESPACE)/marigold-worker
DOCKERFILE     := package/src/compose/Dockerfile

.PHONY: build/api
build/api:
	docker build \
	  --build-arg GIT_TAG=$(TAG) \
	  --target api \
	  -t $(API_IMAGE):$(TAG) \
	  -f $(DOCKERFILE) .

.PHONY: build/cache
build/cache:
	docker build \
	  --build-arg GIT_TAG=$(TAG) \
	  --target cache \
	  -t $(CACHE_IMAGE):$(TAG) \
	  -f $(DOCKERFILE) .

.PHONY: build/worker
build/worker:
	docker build \
	  --build-arg GIT_TAG=$(TAG) \
	  --target worker-cpu \
	  -t $(WORKER_IMAGE):$(TAG) \
	  -f $(DOCKERFILE) .

.PHONY: build/worker-gpu
build/worker-gpu:
	docker build \
	  --build-arg GIT_TAG=$(TAG) \
	  --target worker-gpu \
	  -t $(WORKER_IMAGE):$(TAG)-gpu \
	  -f $(DOCKERFILE) .

.PHONY: build
build: build/api build/cache build/worker build/worker-gpu


# ---------------------------------------------------------------------------
# push targets, alongside the existing build/* ones
# ---------------------------------------------------------------------------

.PHONY: push/api
push/api:
	docker push $(API_IMAGE):$(TAG)

.PHONY: push/cache
push/cache:
	docker push $(CACHE_IMAGE):$(TAG)

.PHONY: push/worker
push/worker:
	docker push $(WORKER_IMAGE):$(TAG)

.PHONY: push/worker-gpu
push/worker-gpu:
	docker push $(WORKER_IMAGE):$(TAG)-gpu

.PHONY: push
push: push/api push/cache push/worker push/worker-gpu



.PHONY: print/api-image print/cache-image print/worker-image print/worker-gpu-image
print/api-image:
	@echo $(API_IMAGE)
print/cache-image:
	@echo $(CACHE_IMAGE)
print/worker-image:
	@echo $(WORKER_IMAGE)
print/worker-gpu-image:
	@echo $(WORKER_IMAGE)
