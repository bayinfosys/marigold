# syntax=docker/dockerfile:1
#
# Marigold -- consolidated multi-stage Dockerfile.
#
# Four build targets:
#   api         -- FastAPI app. No torch at all.
#   cache       -- weight download CLI (model_cli.py). Needs the full
#                  torch-cpu + transformers/diffusers/pydub stack, since
#                  models.load_all() imports every handler module to
#                  populate the provider registry, and several of them
#                  import their heavy dependency at module level. No CUDA,
#                  no ffmpeg -- otherwise the same footprint as worker-cpu.
#   worker-cpu  -- inference worker, CPU torch.
#   worker-gpu  -- inference worker, CUDA + GPU torch.
#
# Build:
#   docker build --target api        -t marigold-api .
#   docker build --target cache      -t marigold-cache .
#   docker build --target worker-cpu -t marigold-worker .
#   docker build --target worker-gpu -t marigold-worker:gpu .

ARG BASE_IMAGE=python:3.12-slim

# ---------------------------------------------------------------------------
# torch-cpu-base: OS + torch-cpu + transformers/diffusers/pydub. Heaviest,
# most stable layers first -- base.requirements.txt (small, changes more
# often) goes last so it never invalidates this.
# Shared ancestor of cache and worker-cpu.
# ---------------------------------------------------------------------------
FROM $BASE_IMAGE AS torch-cpu-base

ENV HF_HUB_DISABLE_PROGRESS_BARS=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    HF_HOME=/tmp \
    HF_HUB_CACHE=/models \
    HF_HUB_OFFLINE=1

WORKDIR /app

COPY package/src/compose/environment/worker-cpu.requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --break-system-packages -r /tmp/requirements.txt

COPY package/src/compose/environment/worker.requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --break-system-packages -r /tmp/requirements.txt

COPY package/src/compose/environment/base.requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --break-system-packages -r /tmp/requirements.txt

# ---------------------------------------------------------------------------
# cuda-python-base: CUDA runtime + Python. Separate OS lineage.
# ---------------------------------------------------------------------------
FROM nvidia/cuda:13.0.0-cudnn-runtime-ubuntu24.04 AS cuda-python-base

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common build-essential wget curl git ca-certificates \
    && add-apt-repository ppa:deadsnakes/ppa && apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-dev python3-pip \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

ENV HF_HUB_DISABLE_PROGRESS_BARS=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    HF_HOME=/tmp \
    HF_HUB_CACHE=/models \
    HF_HUB_OFFLINE=1

WORKDIR /app

# ---------------------------------------------------------------------------
# torch-gpu-base: cuda-python-base + torch-gpu + transformers/diffusers/pydub.
# Same stable-first ordering as torch-cpu-base. Ancestor of worker-gpu only.
# ---------------------------------------------------------------------------
FROM cuda-python-base AS torch-gpu-base

COPY package/src/compose/environment/worker-gpu.requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --break-system-packages -r /tmp/requirements.txt

COPY package/src/compose/environment/worker.requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --break-system-packages -r /tmp/requirements.txt

COPY package/src/compose/environment/base.requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --break-system-packages -r /tmp/requirements.txt

# ---------------------------------------------------------------------------
# base: plain Python, no torch. Ancestor of api only.
# ---------------------------------------------------------------------------
FROM $BASE_IMAGE AS base

ENV HF_HUB_DISABLE_PROGRESS_BARS=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    HF_HOME=/tmp \
    HF_HUB_CACHE=/models \
    HF_HUB_OFFLINE=1

WORKDIR /app

COPY package/src/compose/environment/base.requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --break-system-packages -r /tmp/requirements.txt

# ---------------------------------------------------------------------------
# api: FastAPI app. No torch.
# ---------------------------------------------------------------------------
FROM base AS api

COPY package/src/compose/environment/api.requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --break-system-packages -r /tmp/requirements.txt

COPY package/src .

ARG GIT_TAG=unknown
ENV BUILD_VERSION=${GIT_TAG}

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ---------------------------------------------------------------------------
# cache: weight download CLI. Same Python stack as worker-cpu, no ffmpeg.
# ---------------------------------------------------------------------------
FROM torch-cpu-base AS cache

COPY package/src/compose/environment/cache.requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --break-system-packages -r /tmp/requirements.txt

COPY package/src .

ARG GIT_TAG=unknown
ENV BUILD_VERSION=${GIT_TAG}

CMD ["python3", "-m", "tools.model_cli", "download-weights"]

# ---------------------------------------------------------------------------
# worker-cpu: inference worker, CPU torch.
# ---------------------------------------------------------------------------
FROM torch-cpu-base AS worker-cpu

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY package/src .

ARG GIT_TAG=unknown
ENV BUILD_VERSION=${GIT_TAG}

CMD ["python3", "-c", "from models.entrypoint_handlers import local_handler; local_handler()"]

# ---------------------------------------------------------------------------
# worker-gpu: inference worker, CUDA + GPU torch.
# ---------------------------------------------------------------------------
FROM torch-gpu-base AS worker-gpu

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY package/src .

ARG GIT_TAG=unknown
ENV BUILD_VERSION=${GIT_TAG}

CMD ["python3", "-c", "from models.entrypoint_handlers import local_handler; local_handler()"]
