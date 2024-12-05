#!/bin/bash

#
# install some python packages to a target directory
# - /host-packages is the default target (FIXME: make a var)
# - /tmp/requirements.txt is the default install (FIXME: make a var)

TARGET=/host-packages

# pytorch
pip install \
  --target $TARGET \
  --no-cache-dir \
  --extra-index-url https://download.pytorch.org/whl/cpu torch

# huggingface stuff
pip install \
  --target $TARGET \
  --no-cache-dir \
  transformers \
  sentence-transformers \
  bitsandbytes \
  accelerate \
  sentencepiece \
  protobuf \
  einops

pip install \
  --target $TARGET \
  --no-cache-dir \
  git+https://github.com/huggingface/diffusers.git
#  diffusers

# misc support libraries to avoid complex lambda/docker builds
pip install \
  --target $TARGET \
  --no-cache-dir \
  pydantic
