#!/bin/bash

MODEL_NAME=$1
API_URL="https://huggingface.co/api/models/${MODEL_NAME}"

# Fetch model info (handling redirects)
RESPONSE=$(curl -sL -H "Accept: application/json" "$API_URL")

# Check if the response is empty or invalid
if [[ -z "$RESPONSE" || "$RESPONSE" == "null" ]]; then
    echo "Warning: No data found for model: $MODEL_NAME" >&2
    exit 1
fi

# Process and print JSON (Terraform requires string output)
echo "$RESPONSE" | jq -c \
  --arg model_name "$MODEL_NAME" \
  '{
    organization: (.author // ""),
    license: (.license // .cardData.license // ""),
    sha: (.sha // ""),
    last_modified: (.lastModified // ""),
    tags: (.tags // [] | @json),
    parameter_count: (.safetensors.total // 0 | tostring)
  }'
