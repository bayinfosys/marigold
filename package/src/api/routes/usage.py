"""Usage statistics route."""

from fastapi import Security, APIRouter
from fastapi.responses import JSONResponse

from api.models import UsageResponse
from api.auth import apikey_auth, User


router = APIRouter()


@router.get(
    "/usage/{key}/{period}",
    response_model=UsageResponse,
)
async def usage_stats(key: str, period: str, user=Security(apikey_auth)):
    # Local usage stats not yet implemented -- see TODO_models.md.
    return JSONResponse(status_code=501, content={"status": "error", "message": "not available locally"})
