#!/bin/bash

#
# install some python packages to a target directory
# NB: for local install we set PIP_TARGET to /host-packages (mounted in container)
#     for aws efs, we do not set that var so the packages go to a standard location
#

# pytorch
pip install \
  --no-cache-dir \
  --extra-index-url https://download.pytorch.org/whl/cpu torch

# huggingface stuff
pip install --upgrade \
  --no-cache-dir \
  transformers \
  sentence-transformers \
  bitsandbytes \
  accelerate \
  sentencepiece \
  protobuf \
  einops

pip install --upgrade \
  --no-cache-dir \
  git+https://github.com/huggingface/diffusers.git
#  diffusers

# misc support libraries to avoid complex lambda/docker builds
pip install --upgrade \
  --no-cache-dir \
  pydantic
