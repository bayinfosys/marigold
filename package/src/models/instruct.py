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
import os
from time import perf_counter as clock

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

logger.info("loading torch...")
_T = clock()
import torch

logger.info("torch loaded in %0.2fs", clock() - _T)

from api.models import (InstructMessage, InstructRequest, InstructResponse,
                        InstructRole, ModelType)
from models import BaseModelHandler
from models.cache_model import load_instruct
from shared import record_usage
from transformers import set_seed


class EmptyMessagesError(Exception):
    pass


class InstructModel(BaseModelHandler):

    def __init__(self, modelname: str):
        super().__init__(modelname)
        self.tokenizer, self.model = load_instruct(modelname)

    def process(self, user_id: str, message_id: str, request: dict) -> InstructResponse:
        return self.generate(user_id, InstructRequest.model_validate(request))

    def generate(self, user_id: str, request: InstructRequest) -> InstructResponse:
        """Run one inference pass and return a structured response."""
        if not request.messages:
            logger.warning("[%s] empty messages submitted", user_id)
            raise EmptyMessagesError()

        T = clock()

        # FIXME: add chat_template fallbacks for models without a built-in template
        try:
            inputs = self.tokenizer.apply_chat_template(
                request.messages,
                return_tensors="pt",
                tokenize=False,
                add_generation_prompt=True,
            )
        except IndexError:
            logger.error("bad messages: '%s'", str(request.model_dump()))
            raise
        except ValueError:
            if len(request.messages) > 1:
                prompt_chain = [
                    "{role}: {content}".format(
                        role=message.role.value,
                        content=message.content,
                    )
                    for message in request.messages
                ]
                inputs = "\n".join(prompt_chain)
            elif len(request.messages) == 1:
                inputs = request.messages[0].content
            else:
                inputs = [self.tokenizer.eos_token_id]

            logger.warning("apply_chat_template failed, fell back to manual merge")
        except Exception as e:
            logger.exception("failed to apply chat template [%s]", str(e))
            raise

        model_inputs = self.tokenizer([inputs], return_tensors="pt")

        if request.seed:
            set_seed(request.seed)

        T1 = clock()

        with torch.no_grad():
            model_outputs = self.model.generate(
                model_inputs.input_ids,
                max_new_tokens=request.max_tokens,
                pad_token_id=self.tokenizer.eos_token_id,
                # do_sample=False,  # if sampling is disabled, temperature and top is ignored
                temperature=request.temperature,
                top_k=1,
                top_p=request.top_p,
                repetition_penalty=request.repetition_penalty,
                no_repeat_ngram_size=request.no_repeat_ngram_size,
            )

        iduration = clock() - T1

        generated_ids = [
            output_ids[len(input_ids) :]
            for input_ids, output_ids in zip(model_inputs.input_ids, model_outputs)
        ]

        outputs = self.tokenizer.batch_decode(generated_ids, skip_special_tokens=True)

        input_tokens = model_inputs.input_ids.nelement()
        output_tokens = sum(x.nelement() for x in generated_ids)
        duration = clock() - T

        logger.info(
            "[%s] '%s' %i tokens [in=%i out=%i] in %0.2fs",
            user_id,
            request.model,
            input_tokens + output_tokens,
            input_tokens,
            output_tokens,
            duration,
        )

        usage = record_usage(
            user_id,
            ModelType.INSTRUCT,
            self.modelname,
            duration,
            iduration,
            input_tokens,
            output_tokens,
        )

        return InstructResponse(
            model=self.modelname,
            choices=[InstructMessage(role=InstructRole.ASSISTANT, content=outputs[0])],
            usage=usage,
        )
