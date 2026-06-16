"""Usage statistics route."""

from fastapi import Security
from fastapi.responses import JSONResponse
from fastapi_aws import APIKeyAuthorizer, AWSAPIRouter

from api.models import UsageResponse
from api.auth import apikey_auth, User


router = AWSAPIRouter()


@router.get(
    "/usage/{key}/{period}",
    response_model=UsageResponse,
    aws_lambda_arn="${usage_stats_lambda_arn}",
    aws_iam_arn="${usage_stats_lambda_iam_role_arn}",
)
async def usage_stats(key: str, period: str, user=Security(apikey_auth)):
    # Local usage stats not yet implemented -- see TODO_models.md.
    return JSONResponse(status_code=501, content={"status": "error", "message": "not available locally"})
