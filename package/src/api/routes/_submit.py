"""Shared submission helper for all POST routes.

All submission routes follow the same pattern: extract user_id, call
receiver_logic.handle_submission with app.state backends, return the
appropriate HTTP response.

This module provides _submit() to avoid repeating that pattern in every
route file. model_type is supplied by the caller -- it is fixed by which
route was hit (/gen/instruct is always ModelType.INSTRUCT), not derived
from the request body.
"""

import logging

from fastapi import Request
from fastapi.responses import JSONResponse

from shared.enums import ModelType
from tools.state_machine.receiver_logic import handle_submission

logger = logging.getLogger(__name__)


async def _submit(
    request: Request, user_id: str, body: dict, model_type: ModelType
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

    return JSONResponse(status_code=code, content=resp)
