"""Output polling, deletion, and binary retrieval routes."""

from fastapi import Request, Security, APIRouter
from fastapi.responses import JSONResponse

from api.models import DeleteCacheResponse, PollResponse
from tools.state_machine.receiver_logic import handle_delete, handle_status
from api.auth import apikey_auth

router = APIRouter()


@router.get(
    "/output/{mode}/{task}/{message_id}",
    description="poll for the status and result of a submitted job",
    response_model=PollResponse,
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
