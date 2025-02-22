#!/bin/bash

API_KEY="marfdf8059837cc42cabf87d9ef9d62544824008c79"
HOST="https://api.dev.mdl.bayis.co.uk/v1"
#HOST="http://localhost:8081"
#API_KEY="dummy"
#HOST="5hsiukoyv7.execute-api.eu-west-2.amazonaws.com"


# embed some text
curl  -w "\n" \
  -H "Content-Type: application/json" \
  -H "Authorization: ${API_KEY}" \
  -d '{"model": "sentence-transformers/all-minilm-l6-v2", "input": "hello, world, today"}' \
  ${HOST}/embed/text

curl  -w "\n" \
  -H "Content-Type: application/json" \
  -H "Authorization: ${API_KEY}" \
  -d '{"model": "sentence-transformers/paraphrase-multilingual-mpnet-base-v2", "input": "hello, world, today"}' \
  ${HOST}/embed/text

curl  -w "\n" \
  -H "Content-Type: application/json" \
  -H "Authorization: ${API_KEY}" \
  -d '{"model": "sentence-transformers/sentence-t5-large", "input": "hello, world, today"}' \
  ${HOST}/embed/text


echo fetch embed results
# NB: these ids will change if the above text/model payloads change
#curl -w "\n" -H "Authorization: ${API_KEY}" ${HOST}/embed/text/3f418108cd36041ee11cdad405exxxxx  # 404 test
curl -w "\n" -H "Authorization: ${API_KEY}" ${HOST}/embed/text/3f418108cd36041ee11cdad405ead147
curl -w "\n" -H "Authorization: ${API_KEY}" ${HOST}/embed/text/f3ecd88f0aa5ea723f2b0c748d8e35b2
curl -w "\n" -H "Authorization: ${API_KEY}" ${HOST}/embed/text/409f8bd2c44ff6b05cfdbffd98a8874e
