"""Output polling, deletion, and binary retrieval routes."""

from fastapi import Request, Security
from fastapi.responses import JSONResponse
from fastapi_aws import APIKeyAuthorizer, AWSAPIRouter

from api.models import DeleteCacheResponse, PollResponse
from tools.state_machine.receiver_logic import handle_delete, handle_status
from api.auth import apikey_auth

router = AWSAPIRouter()

_LAMBDA = "${request_receiver_lambda_arn}"
_IAM = "${request_receiver_lambda_iam_role_arn}"


@router.get(
    "/output/{mode}/{task}/{message_id}",
    description="poll for the status and result of a submitted job",
    response_model=PollResponse,
    aws_lambda_arn=_LAMBDA,
    aws_iam_arn=_IAM,
)
async def poll_result(
    request: Request,
    mode: str,
    task: str,
    message_id: str,
    user=Security(apikey_auth),
):
    code, resp = handle_status(
        user_id=user.id,
        message_id=message_id,
        results_cache=request.app.state.results_cache,
    )
    return JSONResponse(status_code=code, content=resp)


@router.delete(
    "/output/{mode}/{task}/{message_id}",
    description="delete a cached job result",
    response_model=DeleteCacheResponse,
    aws_lambda_arn=_LAMBDA,
    aws_iam_arn=_IAM,
)
async def delete_result(
    request: Request,
    mode: str,
    task: str,
    message_id: str,
    user=Security(apikey_auth),
):
    code, resp = handle_delete(
        user_id=user.id,
        message_id=message_id,
        results_cache=request.app.state.results_cache,
    )
    return JSONResponse(status_code=code, content=resp)


@router.get(
    "/output/{mode}/{task}/{message_id}/{field}",
    description="retrieve a named binary output for a completed job",
    aws_s3_bucket="${s3_output_bucket_name}",
    aws_s3_object_key="outputs/{mode}-{task}/{message_id}/{field}",
    aws_iam_arn="${s3_read_output_iam_role_arn}",
)
async def get_output(
    mode: str,
    task: str,
    message_id: str,
    field: str,
    user=Security(apikey_auth),
):
    # Binary output is served directly from S3 on AWS via the decorator.
    # Local binary output retrieval is not yet implemented.
    return JSONResponse(
        status_code=501,
        content={"status": "error", "message": "binary output not available locally"},
    )
