"""general instruct model

works for:
+ mistralai/Mistral-7B-Instruct-v0.2
+ google/codegemma-7b-it (with auth)
+ mistralai/Mixtral-8x22B-Instruct-v0.1
+ tiiuae/falcon-7b-instruct
+ llmware/bling-falcon-1b-0.1

# example input for:
# + "mistralai/Mistral-7B-Instruct-v0.2"
# + "google/codegemma-7b-it" (with auth)
#
#data = [
#    {"role": "user", "content": "What is your favourite condiment?"},
#    {"role": "assistant", "content": "Well, I'm quite partial to a good squeeze of fresh lemon juice. It adds just the right amount of zesty flavour to whatever I'm cooking up in the kitchen!"},
#    {"role": "user", "content": "Do you have mayonnaise recipes?"}
#]
#
# example input for stabilityai/stable-code-instruct-3b
# input = [
#    {"role": "system", "content": "You are a helpful and polite assistant"},
#    {"role": "user", "content": "Write a simple website in HTML. When a user clicks the button, it shows a random joke from a list of 4 jokes."},
#]
"""
import os
import logging
import json
from time import perf_counter as clock

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

logger.info("loading torch...")
T = clock()
import torch

logger.info("torch complete in %0.2fs", (clock() - T))

from transformers import set_seed

from shared import (
    get_userid_from_event,
    lambda_event_to_data,
    mk_resp,
    update_results_table,
    get_memory_usage,
    update_metrics,
)
from api.models import (
    ModelType,
    InstructRequest,
    InstructRole,
    InstructMessage,
    InstructResponse,
    ModelUsageStats,
)

from api.sqs_worker import SQSWorker

LOAD_INSTRUCT_T = clock()
from models.cache_model import load_instruct, ModelNotFoundError
LOAD_INSTRUCT_T = clock() - LOAD_INSTRUCT_T


logger.info("import load_instruct in %0.2fs", LOAD_INSTRUCT_T)


class EmptyMessagesError(Exception):
    pass


class InstructModel:
    def __init__(self, modelname: str):
        self.modelname = modelname
        self.tokenizer, self.model = load_instruct(modelname)

    def generate(self, user_id: str, request: InstructRequest) -> InstructResponse:
        """process an instruct request
        This method is the base method to be called from all lambda, sfn, batch etc handlers
        """
        if not request.messages:
            logger.warning("empty messages submitted")
            raise EmptyMessagesError()

        T = clock()
        # FIXME: add chat_template generators for modelss whihc don't have one (bling-falcon1b,e tc)
        try:
            inputs = self.tokenizer.apply_chat_template(
                request.messages,
                return_tensors="pt",
                tokenize=False,
                add_generation_prompt=True,
            )
        except IndexError:
            logger.error("bad messages? '%s'", str(request.model_dump()))
            raise
        except ValueError:
            if len(request.messages) > 1:
                prompt_chain = [
                    "{role}: {content}".format(
                        role=message.role.value, content=message.content
                    )
                    for message in request.messages
                ]
                inputs = "\n".join(prompt_chain)
            elif len(request.messages) == 1:
                inputs = request.messages[0].content
            else:
                inputs = [self.tokenizer.eos_token_id]

            logger.error(
                "failed to use apply_chat_template, manually merged to '%s'", str(inputs)
            )
        except Exception as e:
            logger.exception(
                "failed to parse: '%s' [%s]", str(request.model_dump()), str(e)
            )
            raise

        logger.debug("templated input: '%s'", str(inputs))
        # inputs = encodeds.to("cpu")

        model_inputs = self.tokenizer([inputs], return_tensors="pt")
        logger.debug("model_inputs: '%s'", str(model_inputs))
        logger.debug("model_inputs: '%i'", model_inputs.input_ids.nelement())

        # FIXME: we can use model.can_generate to check if it is a sequence generator

        # set the random seed
        if request.seed:
            set_seed(request.seed)

        T1 = clock()

        # run inference on the model
        with torch.no_grad():
            # https://huggingface.co/docs/transformers/en/main_classes/text_generation
            model_outputs = self.model.generate(
                model_inputs.input_ids,
                max_new_tokens=request.max_tokens,
                pad_token_id=self.tokenizer.eos_token_id,
                do_sample=False,
                temperature=request.temperature,
                top_k=1,
                top_p=request.top_p,
                repetition_penalty=request.repetition_penalty,
                no_repeat_ngram_size=request.no_repeat_ngram_size,
            )
        iduration = clock() - T1
        logger.debug("model_outputs: '%s'", str(model_outputs))
        logger.debug("model_outputs: '%s'", str(type(model_outputs)))

        generated_ids = [
            output_ids[len(input_ids) :]
            for input_ids, output_ids in zip(model_inputs.input_ids, model_outputs)
        ]
        logger.debug("generated_ids: '%s' [%s:%s]", str(generated_ids), str(type(generated_ids)), str([str(type(x)) for x in generated_ids]))

        outputs = self.tokenizer.batch_decode(generated_ids, skip_special_tokens=True)
        logger.debug("outputs: '%s'", str(outputs))

        input_tokens = model_inputs.input_ids.nelement()
        output_tokens = sum(x.nelement() for x in generated_ids)

        duration = clock() - T

        logger.info(
            "'%s' %i tokens [input=%i, genids=%i] in %0.2fs",
            request.model,
            input_tokens + output_tokens,
            input_tokens,
            output_tokens,
            duration,
        )

        logger.debug(
            "messages: %s, inputs: %s, genids: %s, outputs: %s",
            str(request.messages),
            str(inputs),
            str(generated_ids),
            str(outputs),
        )

        usage = ModelUsageStats(
            duration=duration,
            inference=iduration,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            memory_usage=get_memory_usage(),
        )

        response = InstructResponse(
            model=self.modelname,
            choices=[InstructMessage(role=InstructRole.ASSISTANT, content=outputs[0])],
            usage=usage,
        )

        update_metrics(user_id, ModelType.INSTRUCT, self.modelname, response.usage.model_dump())

        return response


class InstructSQSWorker(SQSWorker):
    """for pulling events from the sqs queue
        trigger the polling lambda with:
    ```json
    {
      "httpMethod": "POST",
      "resource": "/instruct",
      "headers": {
        "x-user-id": "test-user"
      },
      "body": "{\"model\": \"qwen/qwen2-1.5b-instruct\", \"messages\": [{\"role\": \"user\", \"content\": \"Hello world again 20\"}]}"
    }
    ```
        and the message should make it's way here.
    """
    def __init__(self, queue_url: str, model: InstructModel):
        super().init(queue_url, model)

    def handle_message(self, msg):
        try:
            payload = json.loads(msg["Body"])
        except Exception as e:
            logger.error("unable to parse 'Body'")
            raise e

        try:
            user_id = payload["userid"]
            message_id = payload["message_id"]
            request = InstructRequest.model_validate(payload["request"])
        except Exception as e:
            logger.error("unable to parse payload '%s' [%s]", str(e), str(type(e)))
            raise e

        if request.model != self.model.modelname:
            logger.warning(
                "[%s/%s] submitted to wrong model (asked for %s, we are %s)",
                user_id,
                message_id,
                request.model,
                self.model.modelname,
            )
            raise NotImplementedError("this handler does not implement '%s'" % request.model)

        try:
            return user_id, message_id, self.model.generate(user_id, request)
        except Exception as e:
            logger.exception("unable to process message '%s' [%s]", str(e), str(type(e)))
            # NB: we cache the error response to prevent spamming
            raise e


def sqs_handler():
    queue_url = os.environ["AWS_SQS_MODEL_QUEUE"]
    modelname = os.environ["MODELNAME"]

    model = InstructModel(modelname)
    worker = InstructSQSWorker(queue_url, model)

    worker.run()
