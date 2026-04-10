"""Instruction-following / chat models.

Compatible models include:
    qwen/qwen2-0.5b-instruct
    qwen/qwen2-1.5b-instruct
    microsoft/phi-3-mini-128k-instruct
    meta-llama/llama-3.2-1b-instruct
    mistralai/Mistral-7B-Instruct-v0.2
    tiiuae/falcon-7b-instruct
    llmware/bling-falcon-1b-0.1
"""

import logging
from time import perf_counter as clock

import torch
from transformers import set_seed

from api.models import InstructMessage, InstructRequest, InstructResponse
from models.standard_loader import ModelLoaderResult, standard_loader
from shared.enums import ModelMode, ModelType
from shared.models import InstructRole
from shared.registry import BaseModelHandler, model_spec
from shared.usage import record_usage

logger = logging.getLogger(__name__)


class EmptyMessagesError(Exception):
    pass



def load_instruct(modelname: str, cache_dir: str = None, **kwargs) -> ModelLoaderResult:
    """Instruction-following / chat models."""
    from transformers import AutoModelForCausalLM as M
    from transformers import AutoTokenizer as T
    return standard_loader(T, M, modelname, cache_dir=cache_dir, **kwargs)


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

        # FIXME: add chat_template fallbacks for models without a built-in template
        try:
            inputs = self.processor.apply_chat_template(
                request.messages,
                return_tensors="pt",
                tokenize=False,
                add_generation_prompt=True,
            )
        except IndexError:
            logger.error("[%s/%s] bad messages: '%s'", user_id, message_id, str(request.model_dump()))
            raise
        except ValueError:
            # Some models do not have a built-in chat template. Fall back to
            # a plain text merge of the message turns.
            prompt_chain = [
                "{role}: {content}".format(role=message.role.value, content=message.content)
                for message in request.messages
            ]
            inputs = "\n".join(prompt_chain)
            logger.warning("[%s/%s] apply_chat_template failed, fell back to manual merge", user_id, message_id)
        except Exception as e:
            logger.exception("[%s/%s] failed to apply chat template [%s]", user_id, message_id, str(e))
            raise

        model_inputs = self.processor([inputs], return_tensors="pt")

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

        usage = record_usage(
            user_id=user_id,
            model_type=ModelType.INSTRUCT,
            modelname=self.modelname,
            duration=duration,
            inference=iduration,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

        return InstructResponse(
            model=self.modelname,
            choices=[InstructMessage(role=InstructRole.ASSISTANT, content=outputs[0])],
            usage=usage,
        )
