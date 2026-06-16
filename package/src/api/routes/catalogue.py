"""API catalogue routes: OpenAPI spec and model list.

On AWS these are served directly from S3 via API Gateway integrations.
Locally the OpenAPI spec is served by FastAPI's built-in /openapi.json
endpoint, so this route is a no-op stub. models.json is served from
the local filesystem if MODELS_JSON_PATH is set.
"""

import json
import os

from fastapi import Security
from fastapi.responses import JSONResponse
from fastapi_aws import APIKeyAuthorizer, AWSAPIRouter
from api.auth import apikey_auth

router = AWSAPIRouter()


@router.get(
    "/openapi.json",
    aws_s3_bucket="${s3_assets_bucket_name}",
    aws_s3_object_key="openapi.json",
    aws_iam_arn="${s3_read_api_object_iam_role_arn}",
)
async def openapi_spec(user=Security(apikey_auth)):
    # On AWS: served from S3. Locally: FastAPI serves /openapi.json natively.
    return JSONResponse(status_code=200, content={"message": "use /openapi.json"})


@router.get(
    "/models.json",
    aws_s3_bucket="${s3_assets_bucket_name}",
    aws_s3_object_key="models.json",
    aws_iam_arn="${s3_read_api_object_iam_role_arn}",
)
async def model_list(user=Security(apikey_auth)):
    path = os.getenv("MODELS_CONFIG_PATH")

    if path and os.path.exists(path):
        with open(path) as f:
            return JSONResponse(status_code=200, content=json.load(f))

    return JSONResponse(
        status_code=501,
        content={"status": "error", "message": "MODELS_CONFIG_PATH not configured"},
    )
