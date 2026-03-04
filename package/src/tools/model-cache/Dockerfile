ARG BASE_IMAGE=python:3.12

FROM $BASE_IMAGE

COPY package/src/tools/cache_builder_shared.py /opt/cache_builder_shared.py
COPY package/src/tools/cache_builder_aws.py /opt/cache_builder_aws.py
COPY package/src/tools/cache_builder_local.py /opt/cache_builder_local.py

WORKDIR /opt

ENTRYPOINT ["python3", "/opt/cache_builder_aws.py"]

CMD ["build"]
