ARG BASE_IMAGE=python:3.12
# set base image to the environment container

FROM $BASE_IMAGE

COPY package/src/tools/model-cache/main.py /opt/model-cache-builder.py

ENTRYPOINT ["python3", "/opt/model-cache-builder.py"]

CMD ["-h"]
