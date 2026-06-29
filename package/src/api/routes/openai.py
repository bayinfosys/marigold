"""OpenAI-compatible API endpoints.

Provides a subset of the OpenAI REST API as a synchronous wrapper around
the Marigold async submission and polling path. Intended for local
development only -- allows any OpenAI-compatible client (Open WebUI,
LangChain, curl with the openai SDK) to use Marigold without modification.

Endpoints implemented
---------------------
GET  /v1/models                  list available models
POST /v1/chat/completions        instruct/chat inference
POST /v1/embeddings              text embedding

Not implemented
---------------
Streaming (stream=true) -- returns an error asking the client to disable it.
Image generation, audio, fine-tuning -- not mapped.

On AWS
------
This module is not wired into the AWS API Gateway deployment. The async
poll pattern is the correct approach for Lambda-based inference. These
routes are local-only and have no AWS decorator metadata.
"""

import asyncio
import logging
import time
from typing import Literal

from fastapi import HTTPException, Request
from fastapi_aws import AWSAPIRouter
from pydantic import BaseModel
from tools.state_machine.receiver_logic import handle_status, handle_submission

logger = logging.getLogger(__name__)

router = AWSAPIRouter()

_POLL_INTERVAL = 0.5  # seconds between polls
_MAX_WAIT = 300  # seconds before timing out


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    temperature: float = 1.0
    max_tokens: int = 1000
    top_p: float | None = None
    top_k: int | None = None
    stream: bool = False


class ChatCompletionChoice(BaseModel):
    index: int
    message: ChatMessage
    finish_reason: str = "stop"


class UsageStats(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[ChatCompletionChoice]
    usage: UsageStats


class EmbeddingRequest(BaseModel):
    model: str
    input: str | list[str]
    encoding_format: str = "float"


class EmbeddingData(BaseModel):
    object: str = "embedding"
    index: int
    embedding: list[float]


class EmbeddingResponse(BaseModel):
    object: str = "list"
    model: str
    data: list[EmbeddingData]
    usage: UsageStats


class ModelObject(BaseModel):
    id: str
    object: str = "model"
    created: int = 0
    owned_by: str = "marigold"


class ModelsResponse(BaseModel):
    object: str = "list"
    data: list[ModelObject]


# ---------------------------------------------------------------------------
# Shared poll helper
# ---------------------------------------------------------------------------


async def _poll(
    user_id: str,
    message_id: str,
    results_cache,
) -> tuple[int, dict]:
    """Poll until the job is complete or times out.

    Returns (http_status_code, result_dict).
    """
    deadline = time.monotonic() + _MAX_WAIT
    while time.monotonic() < deadline:
        await asyncio.sleep(_POLL_INTERVAL)
        code, resp = handle_status(
            user_id=user_id,
            message_id=message_id,
            results_cache=results_cache,
        )
        if code == 200:
            return 200, resp.get("result", {})
        if code == 404:
            return 404, {}
    return 504, {}


# ---------------------------------------------------------------------------
# Model validation
# ---------------------------------------------------------------------------


def _validate_model(model_name: str, models_config: dict, model_type: str = None) -> None:
    """Validate that model_name exists in models_config.

    Raises HTTPException 400 with a clear error message if not found.
    If model_type is supplied, also checks that the model is of that type
    and lists only models of that type in the error message.

    Args:
        model_name:    HuggingFace model identifier as sent by the client.
        models_config: models_config dict from app.state.
        model_type:    Optional ModelType value to restrict the check.
    """
    from hashlib import md5
    model_hash = md5(model_name.lower().encode()).hexdigest()

    if model_type is not None:
        available = [
            v.get("name") or v.get("model_name")
            for v in models_config.values()
            if (v.get("type") or v.get("model_type")) == model_type
        ]
    else:
        available = [
            v.get("name") or v.get("model_name")
            for v in models_config.values()
        ]

    entry = models_config.get(model_hash)

    if entry is None:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "message": "unknown model '%s'; available%s: %s" % (
                        model_name,
                        (" %s" % model_type) if model_type else "",
                        available,
                    ),
                    "type": "invalid_request_error",
                    "code": "model_not_found",
                }
            },
        )

    if model_type is not None:
        entry_type = entry.get("type") or entry.get("model_type")
        if entry_type != model_type:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "message": "model '%s' is type '%s', not '%s'; available %s models: %s" % (
                            model_name, entry_type, model_type, model_type, available,
                        ),
                        "type": "invalid_request_error",
                        "code": "model_type_mismatch",
                    }
                },
            )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/v1/models", response_model=ModelsResponse)
async def list_models(request: Request) -> ModelsResponse:
    """Return the list of models available in the current deployment.

    Derived from models_config in app.state. Each model appears once
    regardless of type -- clients use the model name to select.
    """
    config = getattr(request.app.state, "models_config", {})
    models = [
        ModelObject(
            id=v.get("name") or v.get("model_name", k),
            created=0,
            owned_by="marigold",
        )
        for k, v in config.items()
    ]
    return ModelsResponse(data=models)


@router.post("/v1/chat/completions")
async def chat_completions(
    body: ChatCompletionRequest,
    request: Request,
) -> ChatCompletionResponse:
    """OpenAI-compatible chat completions.

    Submits to the Marigold instruct queue, polls until complete, and
    returns in OpenAI chat completion format.

    stream=true is not supported. If the client requests streaming,
    a 400 is returned with a message asking it to disable streaming.
    """
    if body.stream:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "message": "streaming is not supported; set stream=false",
                    "type": "invalid_request_error",
                }
            },
        )

    s = request.app.state
    user_id = "openai-local"

    _validate_model(body.model, s.models_config, model_type="instruct")

    submission_body = {
        "model": body.model,
        "messages": [m.model_dump() for m in body.messages],
        "temperature": body.temperature,
        "max_tokens": body.max_tokens,
    }
    if body.top_p is not None:
        submission_body["top_p"] = body.top_p
    if body.top_k is not None:
        submission_body["top_k"] = body.top_k

    code, resp = handle_submission(
        user_id=user_id,
        body=submission_body,
        models_config=s.models_config,
        queue_backend=s.queue_backend,
        notification_backend=s.notification_backend,
        results_cache=s.results_cache,
        topic=s.topic,
    )

    if code != 200 or "message_id" not in resp:
        raise HTTPException(status_code=code, detail={"error": resp})

    status_code, result = await _poll(user_id, resp["message_id"], s.results_cache)

    if status_code != 200:
        raise HTTPException(
            status_code=status_code,
            detail={
                "error": {
                    "message": "inference timed out or failed",
                    "type": "server_error",
                }
            },
        )

    choices = result.get("choices", [])
    content = choices[0].get("content", "") if choices else ""
    usage = result.get("usage", {})
    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)

    return ChatCompletionResponse(
        id="chatcmpl-" + resp["message_id"][:8],
        created=int(time.time()),
        model=body.model,
        choices=[
            ChatCompletionChoice(
                index=0,
                message=ChatMessage(role="assistant", content=content),
                finish_reason=result.get("finish_reason", "stop"),
            )
        ],
        usage=UsageStats(
            prompt_tokens=input_tokens,
            completion_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        ),
    )


@router.post("/v1/embeddings")
async def create_embeddings(body: EmbeddingRequest, request: Request) -> EmbeddingResponse:
    """OpenAI-compatible text embeddings.

    Submits to the Marigold text-embedding queue. Accepts a single string
    or a list of strings -- each is submitted as a separate job and results
    are collected in order.
    """
    logger.info("embeddings request: model=%s input_type=%s", body.model, type(body.input).__name__)

    s = request.app.state
    user_id = "openai-local"

    inputs = body.input if isinstance(body.input, list) else [body.input]
    total_tokens = 0
    embedding_data = []

    _validate_model(body.model, s.models_config, model_type="text-embedding")

    for i, text in enumerate(inputs):
        submission_body = {"model": body.model, "input": text}

        code, resp = handle_submission(
            user_id=user_id,
            body=submission_body,
            models_config=s.models_config,
            queue_backend=s.queue_backend,
            notification_backend=s.notification_backend,
            results_cache=s.results_cache,
            topic=s.topic,
        )

        if code != 200 or "message_id" not in resp:
            raise HTTPException(status_code=400, detail={"error": resp})

        status_code, result = await _poll(user_id, resp["message_id"], s.results_cache)

        if status_code != 200:
            raise HTTPException(
                status_code=status_code,
                detail={
                    "error": {
                        "message": "embedding failed or timed out",
                        "type": "server_error",
                    }
                },
            )

        embedding = result.get("embedding", [])
        usage = result.get("usage", {})
        total_tokens += usage.get("input_tokens", 0)

        embedding_data.append(EmbeddingData(index=i, embedding=embedding))

    return EmbeddingResponse(
        model=body.model,
        data=embedding_data,
        usage=UsageStats(
            prompt_tokens=total_tokens,
            completion_tokens=0,
            total_tokens=total_tokens,
        ),
    )
