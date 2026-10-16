"""Output polling, deletion, and binary retrieval routes."""

import posixpath

from fastapi import Request, Security, APIRouter
from fastapi.responses import JSONResponse, StreamingResponse

from api.models import DeleteCacheResponse, PollResponse
from api.auth import apikey_auth
from shared.receiver_logic import handle_delete, handle_status
from shared.storage import ObjectNotFound, StorageError, get_storage

router = APIRouter()


def _error(code: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=code, content={"status": "error", "message": message})


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
    description="retrieve a named binary output of a completed job",
)
async def get_output(
    request: Request,
    mode: str,
    task: str,
    message_id: str,
    field: str,
    user=Security(apikey_auth),
):
    """Serve one binary output, with the Content-Type stored in its reference.

    202 while the job is queued or running; 404 for an unknown job, a
    failed job, an undeclared field, or an object missing from the store.
    """
    results_cache = request.app.state.results_cache
    full_id = "API#" + message_id

    status = results_cache.get_status(user.id, full_id)

    if status is None:
        return _error(404, "job not found")

    if status not in ("complete", "error"):
        return JSONResponse(status_code=202, content={"status": status, "message_id": message_id})

    if status == "error":
        return _error(404, "job ended in error; it has no outputs")

    response = results_cache.get_response(user.id, full_id)
    ref = (response.get("outputs") or {}).get(field)

    if not ref:
        return _error(404, f"no output field '{field}' on this job")

    key, mimetype = ref["path"], ref["mimetype"]
    storage = get_storage()

    try:
        stat = storage.stat(key)
    except ObjectNotFound:
        return _error(404, "output is missing from the object store")
    except StorageError:
        return _error(502, "object store unavailable")

    headers = {
        "Content-Length": str(stat.size),
        "Content-Disposition": f'inline; filename="{posixpath.basename(key)}"',
    }

    if ref.get("sha256"):
        headers["ETag"] = f'"{ref["sha256"]}"'

    return StreamingResponse(storage.stream(key), media_type=mimetype, headers=headers)
