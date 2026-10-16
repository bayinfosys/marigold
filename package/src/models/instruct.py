"""Instruction-following / chat models.

Compatible models include:
    qwen/qwen2-0.5b-instruct
    qwen/qwen2-1.5b-instruct
    microsoft/phi-3-mini-128k-instruct
    meta-llama/llama-3.2-1b-instruct
    mistralai/Mistral-7B-Instruct-v0.2
    tiiuae/falcon-7b-instruct
    llmware/bling-falcon-1b-0.1

Tool calling
------------
request.tools is passed to apply_chat_template(tools=...) unless
tool_choice is "none". Whether it has any effect depends on the model's
own chat template; a template that ignores tools is not an error.

The generated text is parsed for Hermes-style <tool_call>{...}</tool_call>
blocks, the convention Qwen2.5 and later and the Hermes-Pro family emit.
Each call gets an id from gen_tool_call_id, derived from the message id,
so a cached result carries the same ids every time it is read. A block
that does not parse stays in the content, and its error is listed in
tool_call_errors, so a malformed call is visible to the caller.

Structured output
-----------------
response_format of json_object or json_schema is checked after
generation: the reply must parse as JSON (one surrounding ``` fence is
tolerated) and, for json_schema, validate against the schema. A reply
that fails raises OutputInvalidError, which the worker records with
StatusCode.OUTPUT_INVALID. Nothing is added to the prompt: asking for
JSON is the application's part.

finish_reason
-------------
"tool_calls" when the reply holds tool calls, "length" when generation
stopped at max_tokens, "stop" otherwise.
"""

import json
import logging
import re
from time import perf_counter as clock

import torch
from api.models import InstructRequest, InstructResponse, ResponseFormat
from models.standard_loader import ModelLoaderResult, standard_loader
from shared.enums import ModelMode, ModelType, StatusCode
from shared.models import InstructMessage, InstructRole, InstructToolCall, gen_tool_call_id
from shared.registry import BaseModelHandler, model_spec
from shared.usage import build_usage
from transformers import set_seed

logger = logging.getLogger(__name__)

_TOOL_CALL_RE = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)
_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)

# chat_template_kwargs may not override how the template is called
_RESERVED_TEMPLATE_KWARGS = {"tokenize", "add_generation_prompt", "return_tensors", "tools"}


class EmptyMessagesError(Exception):
    pass


class OutputInvalidError(Exception):
    """The reply does not match the requested response_format."""

    status_code = StatusCode.OUTPUT_INVALID


def load_instruct(modelname: str, cache_dir: str = None, **kwargs) -> ModelLoaderResult:
    """Instruction-following / chat models."""
    from transformers import AutoModelForCausalLM as M
    from transformers import AutoTokenizer as T
    return standard_loader(T, M, modelname, cache_dir=cache_dir, **kwargs)


def parse_tool_calls(
    text: str, message_id: str
) -> tuple[str | None, list[InstructToolCall], list[str]]:
    """Split Hermes-style tool call blocks out of generated text.

    Returns (remaining content, tool calls, errors). A block that parses
    is removed from the content and becomes a call with its id; one that
    does not is left in the content, and its error is returned.
    """
    calls: list[InstructToolCall] = []
    errors: list[str] = []

    def replace(match: re.Match) -> str:
        try:
            call = InstructToolCall.model_validate(json.loads(match.group(1)))
        except ValueError as e:      # JSONDecodeError and ValidationError are both ValueErrors
            errors.append("unparseable tool call: %s" % e)
            return match.group(0)

        calls.append(call.model_copy(update={"id": gen_tool_call_id(message_id, len(calls))}))
        return ""

    remaining = _TOOL_CALL_RE.sub(replace, text).strip()

    return (remaining or None), calls, errors


def check_response_format(content: str | None, response_format: ResponseFormat | None) -> None:
    """Raise OutputInvalidError if the reply does not match response_format."""
    if response_format is None or response_format.type == "text":
        return

    text = (content or "").strip()
    fenced = _FENCE_RE.match(text)
    if fenced:
        text = fenced.group(1)

    excerpt = (content or "")[:500]

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise OutputInvalidError("reply is not valid JSON (%s): %r" % (e, excerpt)) from e

    if response_format.type == "json_object" and not isinstance(data, dict):
        raise OutputInvalidError("reply is JSON but not an object: %r" % excerpt)

    if response_format.type == "json_schema":
        schema = (response_format.json_schema or {}).get("schema")

        if schema:
            import jsonschema

            try:
                jsonschema.validate(data, schema)
            except jsonschema.ValidationError as e:
                raise OutputInvalidError(
                    "reply does not match the schema: %s; reply: %r" % (e.message, excerpt)
                ) from e


def _template_message(m: InstructMessage) -> dict:
    """An InstructMessage as the dict chat templates expect.

    Tool calls go in the nested {"type": "function", "function": {...}}
    shape, with arguments as a dict: Qwen's templates accept it, and
    Llama's accept nothing else.
    """
    d = {"role": m.role, "content": m.content if m.content is not None else ""}

    if m.tool_calls:
        d["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in m.tool_calls
        ]

    if m.tool_call_id:
        d["tool_call_id"] = m.tool_call_id

    if m.name:
        d["name"] = m.name

    return d


@model_spec(
    model_type=ModelType.INSTRUCT,
    mode=ModelMode.GEN,
    output_fields=[],
    loader=load_instruct,
    request_model=InstructRequest,
    response_model=InstructResponse,
    route="/gen/instruct",
)
class InstructModel(BaseModelHandler):

    def __init__(self, modelname: str):
        super().__init__(modelname)

    def _run(self, user_id: str, message_id: str, request: InstructRequest) -> InstructResponse:
        if not request.messages:
            logger.warning("[%s/%s] empty messages submitted", user_id, message_id)
            raise EmptyMessagesError()

        T = clock()

        offer_tools = bool(request.tools) and request.tool_choice != "none"

        template_kwargs = {
            k: v for k, v in request.chat_template_kwargs.items()
            if k not in _RESERVED_TEMPLATE_KWARGS
        }
        if offer_tools:
            template_kwargs["tools"] = request.tools

        try:
            inputs = self.processor.apply_chat_template(
                [_template_message(m) for m in request.messages],
                tokenize=False,
                add_generation_prompt=True,
                **template_kwargs,
            )
        except IndexError:
            logger.error("[%s/%s] bad messages: '%s'", user_id, message_id, str(request.model_dump()))
            raise
        except ValueError:
            # Some models do not have a built-in chat template. Fall back to
            # a plain text merge of the message turns. Tool definitions are
            # dropped in this path -- there is no template to place them in,
            # and a model without a chat template is not a realistic
            # tool-calling candidate regardless.
            prompt_chain = [
                "{role}: {content}".format(role=m.role, content=m.content)
                for m in request.messages
            ]
            inputs = "\n".join(prompt_chain)
            offer_tools = False
            logger.warning("[%s/%s] apply_chat_template failed, fell back to manual merge", user_id, message_id)
        except Exception as e:
            logger.exception("[%s/%s] failed to apply chat template [%s]", user_id, message_id, str(e))
            raise

        model_inputs = self.processor([inputs], return_tensors="pt")
        model_inputs = model_inputs.to(self.model.device)   # ensure device compat

        if request.seed is not None:
            set_seed(request.seed)

        gen_kwargs = dict(
            max_new_tokens=request.max_tokens,
            pad_token_id=self.processor.eos_token_id,
        )

        if request.temperature != 1.0:
            gen_kwargs["do_sample"] = True
            gen_kwargs["temperature"] = request.temperature
        if request.top_k is not None:
            gen_kwargs["do_sample"] = True
            gen_kwargs["top_k"] = request.top_k
        if request.top_p is not None:
            gen_kwargs["do_sample"] = True
            gen_kwargs["top_p"] = request.top_p
        if request.min_p is not None:
            gen_kwargs["do_sample"] = True
            gen_kwargs["min_p"] = request.min_p
        if request.repetition_penalty is not None:
            gen_kwargs["repetition_penalty"] = request.repetition_penalty
        if request.no_repeat_ngram_size is not None:
            gen_kwargs["no_repeat_ngram_size"] = request.no_repeat_ngram_size

        T1 = clock()

        with torch.no_grad():
            model_outputs = self.model.generate(
                model_inputs.input_ids,
                **gen_kwargs,
            )

        iduration = clock() - T1

        generated_ids = [
            output_ids[len(input_ids):]
            for input_ids, output_ids in zip(model_inputs.input_ids, model_outputs)
        ]

        outputs = self.processor.batch_decode(generated_ids, skip_special_tokens=True)

        input_tokens = model_inputs.input_ids.nelement()
        output_tokens = sum(x.nelement() for x in generated_ids)
        duration = clock() - T

        logger.info(
            "[%s/%s] '%s' %i tokens [in=%i out=%i] in %0.2fs",
            user_id,
            message_id,
            self.modelname,
            input_tokens + output_tokens,
            input_tokens,
            output_tokens,
            duration,
        )

        usage = build_usage(
            user_id=user_id,
            model_type=ModelType.INSTRUCT,
            modelname=self.modelname,
            duration=duration,
            inference=iduration,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            load_time_ms=self.load_time_ms,
            model_size_bytes=self.model_size_bytes,
        )

        if offer_tools:
            content, tool_calls, tool_call_errors = parse_tool_calls(outputs[0], message_id)
        else:
            content, tool_calls, tool_call_errors = (outputs[0].strip() or None), [], []

        for error in tool_call_errors:
            logger.warning("[%s/%s] %s", user_id, message_id, error)

        # A turn that calls tools is not the final answer, so the
        # requested format applies only to a reply without tool calls.
        if not tool_calls:
            check_response_format(content, request.response_format)

        if tool_calls:
            finish_reason = "tool_calls"
        elif len(generated_ids[0]) >= request.max_tokens:
            finish_reason = "length"
        else:
            finish_reason = "stop"

        return InstructResponse(
            model=self.modelname,
            choices=[
                InstructMessage(
                    role=InstructRole.ASSISTANT,
                    content=content,
                    tool_calls=tool_calls,
                )
            ],
            finish_reason=finish_reason,
            tool_call_errors=tool_call_errors,
            usage=usage,
        )
