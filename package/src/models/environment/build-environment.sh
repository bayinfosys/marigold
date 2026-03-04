#!/bin/bash

#
# install some python packages to a target directory
# NB: for local install we set PIP_TARGET to /host-packages (mounted in container)
#     for aws efs, we do not set that var so the packages go to a standard location
#

# pytorch
pip install \
  --no-cache-dir \
  --break-system-packages \
  --extra-index-url https://download.pytorch.org/whl/cpu \
  torch

# huggingface stuff
pip install --upgrade \
  --no-cache-dir \
  --break-system-packages \
  transformers \
  sentence-transformers \
  bitsandbytes \
  accelerate \
  sentencepiece \
  protobuf \
  einops

pip install --upgrade \
  --no-cache-dir \
  --break-system-packages \
  diffusers
#  git+https://github.com/huggingface/diffusers.git

# misc support libraries
pip install --upgrade \
  --no-cache-dir \
  --break-system-packages \
  pydantic \
  pydub \
  pyyaml
