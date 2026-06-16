"""Shared submission helper for all POST routes.

All submission routes follow the same pattern: extract user_id, call
receiver_logic.handle_submission with app.state backends, return the
appropriate HTTP response.

This module provides _submit() to avoid repeating that pattern in every
route file.
"""

import logging

from fastapi import Request
from fastapi.responses import JSONResponse

from tools.state_machine.receiver_logic import handle_submission

logger = logging.getLogger(__name__)


async def _submit(request: Request, user_id: str, body: dict) -> JSONResponse:
    """Call handle_submission with backends from app.state.

    Returns a JSONResponse with the appropriate status code. On AWS
    this function is never called -- API Gateway intercepts first.
    """
    s = request.app.state
    code, resp = handle_submission(
        user_id=user_id,
        body=body,
        models_config=s.models_config,
        queue_backend=s.queue_backend,
        notification_backend=s.notification_backend,
        results_cache=s.results_cache,
        topic=s.topic,
    )
    return JSONResponse(status_code=code, content=resp)
