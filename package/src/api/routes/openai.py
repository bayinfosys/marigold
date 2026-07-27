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

Streaming
---------
stream=true is accepted. Marigold's generation path (instruct.py) still
runs a single blocking call per request and does not stream tokens as
they are produced. When stream=true is set, the full result is sent as
a fixed sequence of SSE chunks (role, then content and/or tool_calls,
then a final chunk carrying finish_reason) followed by [DONE], matching
the framing an OpenAI-compatible client expects. This is not token-level
streaming. Real token-level streaming requires changes to instruct.py
and worker.py and is not implemented here.

Tool calling
------------
Tool definitions in a request's `tools` field are passed straight
through to /gen/instruct, which passes them to apply_chat_template --
see instruct.py for what that does and does not guarantee. Only one
tool call per assistant turn round-trips correctly: InstructMessage has
no field for OpenAI's tool_call_id, so a turn with multiple simultaneous
tool calls has no way to match a tool result back to the call that
produced it. tool_call_id is accepted on incoming messages for OpenAI
API compatibility but is dropped when submitting to /gen/instruct.

Not implemented
----------------
Image generation, audio, fine-tuning -- not mapped.
"""

import asyncio
import json
import logging
import time
from typing import Literal

from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi_aws import AWSAPIRouter
from models.catalogue import get_models_by_type
from pydantic import BaseModel
from shared.enums import ModelType
from tools.state_machine.receiver_logic import handle_status, handle_submission

logger = logging.getLogger(__name__)

router = AWSAPIRouter()

_POLL_INTERVAL = 0.5  # seconds between polls
_MAX_WAIT = 300  # seconds before timing out


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class ToolCallFunction(BaseModel):
    name: str
    arguments: str  # JSON-encoded string, per OpenAI convention


class ToolCall(BaseModel):
    id: str
    type: str = "function"
    function: ToolCallFunction


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = (
        None  # accepted for compatibility, dropped before submission -- see module docstring
    )


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    temperature: float = 1.0
    max_tokens: int = 1000
    top_p: float | None = None
    top_k: int | None = None
    stream: bool = False
    tools: list[dict] | None = None
    tool_choice: str | dict | None = None


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


class ChatCompletionChunkDelta(BaseModel):
    role: str | None = None
    content: str | None = None
    tool_calls: list[ToolCall] | None = None


class ChatCompletionChunkChoice(BaseModel):
    index: int = 0
    delta: ChatCompletionChunkDelta
    finish_reason: str | None = None


class ChatCompletionChunk(BaseModel):
    id: str
    object: str = "chat.completion.chunk"
    created: int
    model: str
    choices: list[ChatCompletionChunkChoice]


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
# Message shape conversion -- OpenAI <-> InstructMessage
# ---------------------------------------------------------------------------


def _to_instruct_message(m: ChatMessage) -> dict:
    """Convert an OpenAI-shaped ChatMessage into the dict shape
    /gen/instruct's InstructMessage expects.

    tool_call_id is dropped here -- InstructMessage has no field for it.
    See the module docstring for the single-tool-call-per-turn limitation
    this implies.
    """
    d = {"role": m.role, "content": m.content}
    if m.tool_calls:
        d["tool_calls"] = [
            {
                "name": tc.function.name,
                "arguments": (
                    json.loads(tc.function.arguments) if tc.function.arguments else {}
                ),
            }
            for tc in m.tool_calls
        ]
    return d


def _from_instruct_tool_calls(
    raw_tool_calls: list[dict], message_id: str
) -> list[ToolCall]:
    """Convert InstructMessage-shaped tool_calls (arguments as a dict) into
    OpenAI-shaped ToolCall objects (arguments as a JSON-encoded string).
    """
    return [
        ToolCall(
            id="call_%s_%d" % (message_id[:8], i),
            function=ToolCallFunction(
                name=tc.get("name", ""),
                arguments=json.dumps(tc.get("arguments", {})),
            ),
        )
        for i, tc in enumerate(raw_tool_calls)
    ]


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


async def _sse_chunks(
    completion_id: str,
    created: int,
    model: str,
    content: str | None,
    tool_calls: list[ToolCall] | None,
    finish_reason: str,
):
    """Yield a fixed sequence of SSE chunks for a completed (non-token-streamed) result.

    Marigold's generation path is still a single blocking call per request --
    this does not stream tokens as they are produced. It produces the
    chunk shape and framing an OpenAI-compatible client expects, so
    stream=true stops failing with a 400. Real token-level streaming is a
    separate, larger change to instruct.py and worker.py, not made here.
    """
    role_chunk = ChatCompletionChunk(
        id=completion_id,
        created=created,
        model=model,
        choices=[
            ChatCompletionChunkChoice(
                delta=ChatCompletionChunkDelta(role="assistant"), finish_reason=None
            )
        ],
    )
    yield "data: %s\n\n" % role_chunk.model_dump_json(exclude_none=True)

    if content is not None or tool_calls:
        body_chunk = ChatCompletionChunk(
            id=completion_id,
            created=created,
            model=model,
            choices=[
                ChatCompletionChunkChoice(
                    delta=ChatCompletionChunkDelta(
                        content=content, tool_calls=tool_calls
                    ),
                    finish_reason=None,
                )
            ],
        )
        yield "data: %s\n\n" % body_chunk.model_dump_json(exclude_none=True)

    final_chunk = ChatCompletionChunk(
        id=completion_id,
        created=created,
        model=model,
        choices=[
            ChatCompletionChunkChoice(
                delta=ChatCompletionChunkDelta(), finish_reason=finish_reason
            )
        ],
    )
    yield "data: %s\n\n" % final_chunk.model_dump_json(exclude_none=True)

    yield "data: [DONE]\n\n"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

_models = None


@router.get("/v1/models", response_model=ModelsResponse)
async def list_models(request: Request) -> ModelsResponse:
    """Return the list of models available in the current deployment."""
    global _models

    if _models is None:
        _db_models = get_models_by_type(
            backend=request.app.state.table_backend,
            table=request.app.state.model_catalogue_table,
            model_type=ModelType.INSTRUCT,
        )

        _models = [
            ModelObject(id=m.name, created=0, owned_by=m.provider.value)
            for m in _db_models
        ]

    return ModelsResponse(data=_models)


@router.post("/v1/chat/completions")
async def chat_completions(
    body: ChatCompletionRequest,
    request: Request,
):
    """OpenAI-compatible chat completions.

    Submits to the Marigold instruct queue, polls until complete, and
    returns in OpenAI chat completion format.

    stream=true is accepted -- see the module docstring. The result is
    still produced by a single blocking poll; streaming only changes
    how that finished result is framed in the response.

    tools, if present, is passed straight through to /gen/instruct --
    see the module docstring for the single-tool-call-per-turn limitation.
    """
    table_backend = request.app.state.table_backend
    queue_backend = request.app.state.queue_backend
    results_cache = request.app.state.results_cache
    table = request.app.state.model_catalogue_table

    user_id = "openai-local"

    submission_body = {
        "model": body.model,
        "messages": [_to_instruct_message(m) for m in body.messages],
        "temperature": body.temperature,
        "max_tokens": body.max_tokens,
    }
    if body.top_p is not None:
        submission_body["top_p"] = body.top_p
    if body.top_k is not None:
        submission_body["top_k"] = body.top_k
    if body.tools is not None:
        submission_body["tools"] = body.tools

    code, resp = handle_submission(
        user_id=user_id,
        body=submission_body,
        model_type=ModelType.INSTRUCT,
        catalogue_backend=table_backend,
        catalogue_table=table,
        queue_backend=queue_backend,
        notification_backend=None,
        results_cache=results_cache,
        topic=None,  # s.topic,
    )

    if code != 200 or "message_id" not in resp:
        raise HTTPException(status_code=code, detail={"error": resp})

    status_code, result = await _poll(user_id, resp["message_id"], results_cache)

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
    choice0 = choices[0] if choices else {}
    content = choice0.get("content")
    raw_tool_calls = choice0.get("tool_calls") or []
    tool_calls = (
        _from_instruct_tool_calls(raw_tool_calls, resp["message_id"])
        if raw_tool_calls
        else None
    )

    usage = result.get("usage", {})
    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    finish_reason = "tool_calls" if tool_calls else result.get("finish_reason", "stop")
    completion_id = "chatcmpl-" + resp["message_id"][:8]
    created = int(time.time())

    if body.stream:
        return StreamingResponse(
            _sse_chunks(
                completion_id, created, body.model, content, tool_calls, finish_reason
            ),
            media_type="text/event-stream",
        )

    return ChatCompletionResponse(
        id=completion_id,
        created=created,
        model=body.model,
        choices=[
            ChatCompletionChoice(
                index=0,
                message=ChatMessage(
                    role="assistant", content=content, tool_calls=tool_calls
                ),
                finish_reason=finish_reason,
            )
        ],
        usage=UsageStats(
            prompt_tokens=input_tokens,
            completion_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        ),
    )


@router.post("/v1/embeddings")
async def create_embeddings(
    body: EmbeddingRequest, request: Request
) -> EmbeddingResponse:
    """OpenAI-compatible text embeddings.

    Submits to the Marigold text-embedding queue. Accepts a single string
    or a list of strings -- each is submitted as a separate job and results
    are collected in order.
    """
    logger.info(
        "embeddings request: model=%s input_type=%s",
        body.model,
        type(body.input).__name__,
    )

    table_backend = request.app.state.table_backend
    queue_backend = request.app.state.queue_backend
    results_cache = request.app.state.results_cache
    table = request.app.state.model_catalogue_table

    user_id = "openai-local"

    inputs = body.input if isinstance(body.input, list) else [body.input]
    total_tokens = 0
    embedding_data = []

    for i, text in enumerate(inputs):
        submission_body = {"model": body.model, "input": text}

        code, resp = handle_submission(
            user_id=user_id,
            body=submission_body,
            model_type=ModelType.TEXT_EMBEDDING,
            catalogue_backend=table_backend,
            catalogue_table=table,
            queue_backend=queue_backend,
            notification_backend=None,
            results_cache=results_cache,
            topic=None,  # s.topic,
        )

        if code != 200 or "message_id" not in resp:
            raise HTTPException(status_code=400, detail={"error": resp})

        status_code, result = await _poll(user_id, resp["message_id"], results_cache)

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
