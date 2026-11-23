"""API catalogue routes: the model list and one model's detail.

The detail adds to the catalogue entry what applies to the model and
what has happened to it: its resolved settings, from the application
and the host's [models], its recent lifecycle events, and a summary of
all usage recorded for it.
"""


from fastapi import Request, Security, APIRouter
from fastapi.responses import JSONResponse
from marigold.api.auth import apikey_auth

from marigold.shared.db_models import WorkerEvent
from marigold.shared.enums import ModelType
from marigold.shared.model_settings import resolve_settings
from marigold.shared.usage import model_usage_summary
from marigold.shared.catalogue import get_all_models, get_model


router = APIRouter()

# Events returned with a model's detail, newest first.
RECENT_EVENTS = 50


@router.get("/models")
async def model_list(request: Request, user=Security(apikey_auth)):
    table = request.app.state.model_catalogue_table
    backend = request.app.state.table_backend
    items = get_all_models(backend, table)

    return JSONResponse(status_code=200, content=[i.model_dump(mode="json") for i in items])


@router.get("/models/{model_type}/{model_name:path}")
async def model_detail(
    request: Request, model_type: ModelType, model_name: str, user=Security(apikey_auth)
):
    table = request.app.state.model_catalogue_table
    backend = request.app.state.table_backend

    item = get_model(backend, table, model_type, model_name)

    if item is None:
        return JSONResponse(
            status_code=404,
            content={"status": "error", "message": f"no such model: {model_type}/{model_name}"},
        )

    events = request.app.state.table_backend.query(
        request.app.state.events_table,
        WorkerEvent,
        model_hash=item.hash,
        limit=RECENT_EVENTS,
        reverse=True,
    )

    content = item.model_dump(mode="json")
    content["settings"] = resolve_settings(
        item.type, item.name, item.settings, request.app.state.host_settings
    )
    content["events"] = [
        event.model_dump(mode="json", include={"timestamp", "event_type", "message_id", "payload"})
        for event in events
    ]
    content["usage"] = model_usage_summary(
        request.app.state.connection, request.app.state.usage_table, item.type, item.name
    )

    return JSONResponse(status_code=200, content=content)
