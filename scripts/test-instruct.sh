#!/bin/bash

API_KEY="marfdf8059837cc42cabf87d9ef9d62544824008c79"
HOST="https://api.dev.mdl.bayis.co.uk/v1"

# get the openapi spec
curl  -w "\n" -H "Authorization: ${API_KEY}" -H "Content-Type: application/json" ${HOST}/instruct -d '{ "model": "qwen/qwen2-05b-instruct", "messages": [{"role": "user", "content": "hello"}]}'
