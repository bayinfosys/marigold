"""API catalogue routes: OpenAPI spec and model list.

On AWS these are served directly from S3 via API Gateway integrations.
Locally the OpenAPI spec is served by FastAPI's built-in /openapi.json
endpoint, so this route is a no-op stub. models.json is served from
the local filesystem if MODELS_JSON_PATH is set.
"""

import json
import os

from fastapi import Request, Security, APIRouter
from fastapi.responses import JSONResponse
from api.auth import apikey_auth

from shared.enums import ModelType
from models.catalogue import get_all_models


router = APIRouter()


@router.get("/models")
async def model_list(request: Request, user=Security(apikey_auth)):
    table = request.app.state.model_catalogue_table
    backend = request.app.state.table_backend
    items = get_all_models(backend, table)

    return JSONResponse(status_code=200, content=[i.model_dump(mode="json") for i in items])


@router.get("/models/{model_type}/{model_name:path}")
async def model_detail(
    request: Request, model_type: ModelType, model_name: str, user=Security(apikey_auth)
):
    table = request.app.state.model_catalogue_table
    backend = request.app.state.table_backend

    item = get_model(backend, table, model_type, model_name)

    if item is None:
        return JSONResponse(
            status_code=404,
            content={"status": "error", "message": f"no such model: {model_type}/{model_name}"},
        )

    return JSONResponse(status_code=200, content=item.model_dump(mode="json"))
