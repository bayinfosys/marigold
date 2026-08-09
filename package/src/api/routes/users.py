"""User-facing routes: API key management and waitlist."""

from fastapi import Security, APIRouter
from fastapi.responses import JSONResponse

from api.auth import apikey_auth, User


cognito_auth = None


router = APIRouter()


@router.post(
    "/users/keys",
    description="create an API key for programmatic access",
)
async def create_api_key(user=Security(cognito_auth)):
    return JSONResponse(status_code=501, content={"status": "error", "message": "not available locally"})


@router.get(
    "/users/keys",
    description="list API keys for the current user",
)
async def list_api_keys(user=Security(cognito_auth)):
    return JSONResponse(status_code=501, content={"status": "error", "message": "not available locally"})


@router.delete(
    "/users/keys/{key_id}",
    description="delete an API key",
)
async def delete_api_key(key_id: str, user=Security(cognito_auth)):
    return JSONResponse(status_code=501, content={"status": "error", "message": "not available locally"})
