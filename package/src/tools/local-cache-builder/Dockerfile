ARG BASE_IMAGE=python:3.12
# set base iamge the python version
# mount the host site-packages target directory to /host-packages

FROM $BASE_IMAGE

COPY models/env/requirements.txt /tmp/requirements.txt
COPY package/src/tools/local-cache-builder/build-cache.sh /usr/local/bin/build-cache.sh

ENTRYPOINT ["bash", "-c"]

CMD ["build-cache.sh"]
