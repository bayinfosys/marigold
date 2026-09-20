"""Shared submission helper for all POST routes.

All submission routes follow the same pattern: extract user_id, call
receiver_logic.handle_submission with app.state backends, return the
appropriate HTTP response.

This module provides _submit() to avoid repeating that pattern in every
route file. model_type and mode are supplied by the caller -- both are
fixed by which route was hit (/gen/instruct is always GEN + INSTRUCT),
not derived from the request body or the request path.
"""

import logging

from fastapi import Request
from fastapi.responses import JSONResponse

from shared.enums import ModelMode, ModelType
from shared.receiver_logic import handle_submission

logger = logging.getLogger(__name__)


async def _submit(
    request: Request,
    user_id: str,
    body: dict,
    model_type: ModelType,
    mode: ModelMode = ModelMode.GEN,
) -> JSONResponse:
    """Call handle_submission with backends from app.state."""
    table_backend = request.app.state.table_backend
    queue_backend = request.app.state.queue_backend
    notification_backend = request.app.state.notification_backend
    results_cache = request.app.state.results_cache
    table = request.app.state.model_catalogue_table
    topic = request.app.state.topic

    code, resp = handle_submission(
        user_id=user_id,
        body=body,
        model_type=model_type,
        catalogue_backend=table_backend,
        catalogue_table=table,
        queue_backend=queue_backend,
        notification_backend=notification_backend,
        results_cache=results_cache,
        topic=topic,
    )

    headers = {}

    # Location points at the poll route for this job, so a client never has
    # to know how /output/ paths are assembled. Only meaningful when a job
    # exists: error responses carry no message_id.
    if code < 400 and "message_id" in resp:
        headers["Location"] = (
            f"/output/{mode.value}/{model_type.value}/{resp['message_id']}"
        )

    return JSONResponse(status_code=code, content=resp, headers=headers)
