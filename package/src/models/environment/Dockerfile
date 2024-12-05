# NB: this version of python is the aws lambda runtime environment
#     so the cached packages on efs must be compatible with this
#     (i.e., the path: /mnt/shared/packages/lib/python3.11/site-packages)
#     which must be made by the cache-builder on aws and the local cache
ARG BASE_IMAGE="public.ecr.aws/lambda/python:3.12"
FROM $BASE_IMAGE AS pytcpu

ENV HF_HUB_DISABLE_PROGRESS_BARS=1
ENV HF_HUB_DISABLE_TELEMETRY=1
ENV HF_HOME=/tmp
# location of mounted model storage
ENV HF_HUB_CACHE=/models
# no download model (disable this for caching process)
ENV HF_HUB_OFFLINE=1


# modelname envar sets the cache loading
ENV MODELNAME="UNSET"
# load in 4bit for quantized models
ENV LOAD_IN_4BIT=0
# remote code model definitions
ENV REMOTE_CODE=0
# use_fast is for GPTNeoXTokenizer ValueError
ENV USE_FAST=0

COPY ./package/src .

# we override the entrypoint because aws lambda function definitions can
# redefine them, whereas aws job definitions cannot; so by setting to 'bash'
# we can use the same container in lambda and batch, providing we restore
# the entrypoint in the lambda function.
ENTRYPOINT "bash"
# original entrypoint is:
# ENTRYPOINT "/lambda-entrypoint.sh"

# FIXME: each model type has a different main handler, make an error here
CMD ["main.lambda_handler"]
