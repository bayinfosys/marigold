"""User-facing routes: API key management and waitlist."""

from fastapi import Security
from fastapi.responses import JSONResponse
from fastapi_aws import APIKeyAuthorizer, AWSAPIRouter

from api.auth import apikey_auth, User

# Cognito auth is not wired locally.
cognito_auth = None

router = AWSAPIRouter()


@router.post(
    "/users/keys",
    description="create an API key for programmatic access",
    aws_lambda_arn="${key_management_lambda_arn}",
    aws_iam_arn="${key_management_lambda_iam_role_arn}",
)
async def create_api_key(user=Security(cognito_auth)):
    return JSONResponse(status_code=501, content={"status": "error", "message": "not available locally"})


@router.get(
    "/users/keys",
    description="list API keys for the current user",
    aws_lambda_arn="${key_management_lambda_arn}",
    aws_iam_arn="${key_management_lambda_iam_role_arn}",
)
async def list_api_keys(user=Security(cognito_auth)):
    return JSONResponse(status_code=501, content={"status": "error", "message": "not available locally"})


@router.delete(
    "/users/keys/{key_id}",
    description="delete an API key",
    aws_lambda_arn="${key_management_lambda_arn}",
    aws_iam_arn="${key_management_lambda_iam_role_arn}",
)
async def delete_api_key(key_id: str, user=Security(cognito_auth)):
    return JSONResponse(status_code=501, content={"status": "error", "message": "not available locally"})


@router.post(
    "/users/waitlist",
    description="join the waitlist for a feature",
    summary="waitlist",
    aws_dynamodb_table_name="${users_table_name}",
    aws_dynamodb_pk_pattern="WAITLIST",
    aws_dynamodb_sk_pattern="EMAIL#$body.email#SOURCE#$body.source",
    aws_dynamodb_fields="""
    "email": { "S": "$body.email" },
    "source": { "S": "$body.source" },
    "created_at": { "S": "$context.requestTimeEpoch" },
    "source_ip": { "S": "$context.identity.sourceIp" },
    "user_agent": { "S": "$context.identity.userAgent" }
    """,
    aws_iam_arn="${users_table_iam_role_arn}",
)
async def join_waitlist():
    return JSONResponse(status_code=501, content={"status": "error", "message": "not available locally"})
