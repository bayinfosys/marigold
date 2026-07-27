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
If request.tools is set, tool definitions are passed to
apply_chat_template(tools=...). Whether this has any effect depends on
the model's own chat template -- templates that don't reference `tools`
in their Jinja source simply ignore the argument. This is not an error
and needs no capability check beforehand; the tools kwarg is a formal
parameter of apply_chat_template() itself since transformers 4.42.0; it
does not fail on a template that ignores it.

What is checked afterward is the generated text: only the Hermes-style
<tool_call>{...}</tool_call> convention is parsed here (this is what
Qwen2.5+ and Hermes-Pro-family models emit natively). A model that does
not support tools, or one using a different tool-call convention
(Llama's JSON format, Mistral's, etc.), simply produces no tool_calls --
indistinguishable from a model that supports tools but chose not to call
one for this request. Both cases are handled identically: the caller
gets a normal text answer back, and no error is raised on account of
tools being requested but unsupported.
"""

import json
import logging
import re
from time import perf_counter as clock

import torch
from api.models import InstructMessage, InstructRequest, InstructResponse
from models.standard_loader import ModelLoaderResult, standard_loader
from shared.enums import ModelMode, ModelType
from shared.models import InstructRole
from shared.registry import BaseModelHandler, model_spec
from shared.usage import build_usage
from transformers import set_seed

logger = logging.getLogger(__name__)

_TOOL_CALL_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)


class EmptyMessagesError(Exception):
    pass


def load_instruct(modelname: str, cache_dir: str = None, **kwargs) -> ModelLoaderResult:
    """Instruction-following / chat models."""
    from transformers import AutoModelForCausalLM as M
    from transformers import AutoTokenizer as T
    return standard_loader(T, M, modelname, cache_dir=cache_dir, **kwargs)


def _parse_hermes_tool_calls(text: str) -> tuple[str | None, list[dict]]:
    """Parse Hermes-style <tool_call>{...}</tool_call> blocks out of raw
    generated text.

    Returns (remaining_content, tool_calls). remaining_content has the
    tool_call blocks stripped out and is None if nothing else remained.
    tool_calls is a list of {"name": ..., "arguments": {...}} dicts,
    empty if the model produced none -- there is no error case here,
    only "found none".

    Covers only models whose chat template emits this specific
    convention. See the module docstring for what happens with others.
    """
    matches = _TOOL_CALL_RE.findall(text)
    tool_calls = []

    for m in matches:
        try:
            tool_calls.append(json.loads(m))
        except json.JSONDecodeError:
            logger.warning("malformed tool_call block, discarding: %s", m)

    remaining = _TOOL_CALL_RE.sub("", text).strip()

    return (remaining or None), tool_calls


def parse_tool_calls(text: str):
    return _parse_hermes_tool_calls(text)


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

        template_kwargs = {}
        if getattr(request, "tools", None):
            template_kwargs["tools"] = request.tools

        # FIXME: add chat_template fallbacks for models without a built-in template
        try:
            messages_as_dicts = []
            for m in request.messages:
                d = {"role": m.role, "content": m.content}
                if getattr(m, "tool_calls", None):
                    d["tool_calls"] = m.tool_calls
                messages_as_dicts.append(d)

            # apply chat template requires dicts, not our pydantic type
            inputs = self.processor.apply_chat_template(
                messages_as_dicts,
                return_tensors="pt",
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

        # TODO: should we track tool calls in the usage?
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

        # extract any tool calls and separated content
        content, tool_calls = parse_tool_calls(outputs[0])

        return InstructResponse(
            model=self.modelname,
            choices=[
                InstructMessage(
                    role=InstructRole.ASSISTANT,
                    content=content,
                    tool_calls=tool_calls,
                )
            ],
            usage=usage,
        )
