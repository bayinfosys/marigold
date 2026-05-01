"""HTTP handler

Handles HTTP requests to APIs and whatnot
"""
import httpx
from shared.enums import ModelMode, ModelType
from shared.registry import BaseModelHandler, model_spec
from models.standard_loader import ModelLoaderResult
from shared.models import HttpRequest, HttpResponse


def load_http(modelname: str, cache_dir: str = None, **kwargs) -> ModelLoaderResult:
    return ModelLoaderResult(processor=None, model=None)


@model_spec(
    model_type=ModelType.HTTP,
    mode=ModelMode.GEN,
    output_fields=[],
    loader=load_http,
    request_model=HttpRequest,
    response_model=HttpResponse,
    route="/gen/http",
)
class HttpHandler(BaseModelHandler):

    def _run(self, user_id: str, message_id: str, request: HttpRequest) -> HttpResponse:
        """send a request to the endpoint and return the response
        TODO: add a HttpRequest.to_request() method which creates a prepared message (as in request lib)
        TODO: ensure the `content-type` header is set appropriately for POST body contents(should we?)
        """
        with httpx.Client(timeout=request.timeout) as client:
            response = client.request(
                method=request.method,
                url=request.url,
                headers=request.headers,
                json=request.body if request.method != "GET" else None,
            )
        return HttpResponse.from_response(response)
