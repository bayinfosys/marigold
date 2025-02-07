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

import torch

from time import perf_counter as clock

from transformers import set_seed

from shared import get_userid_from_event, lambda_event_to_data, mk_resp, update_results_table, get_memory_usage, update_metrics
from api.models import (
    ModelType,
    InstructRequest,
    InstructRole,
    InstructMessage,
    InstructResponse,
    ModelUsageStats,
)

LOAD_INSTRUCT_T = clock()
from models.cache_model import load_instruct, ModelNotFoundError

LOAD_INSTRUCT_T = clock() - LOAD_INSTRUCT_T


logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL") or "INFO")

logger.info("import load_instruct in %0.2fs", LOAD_INSTRUCT_T)


class EmptyMessagesError(Exception):
    pass


def instruct_process(user_id: str, instruct_request: InstructRequest) -> InstructResponse:
    """process an instruct request
    This method is the base method to be called from all lambda, sfn, batch etc handlers
    """
    if not instruct_request.messages:
        logger.warning("empty messages submitted")
        raise EmptyMessagesError()

    T = clock()

    try:
        tokenizer, model = load_instruct(instruct_request.model)
    except ModelNotFoundError as e:
        logger.critical("'%s' failed to load tokenizer", instruct_request.model)
        raise e

    logger.info("'%s' loaded in %0.2fs", instruct_request.model, (clock() - T))

    T = clock()
    # FIXME: add chat_template generators for modelss whihc don't have one (bling-falcon1b,e tc)
    try:
        inputs = tokenizer.apply_chat_template(
            instruct_request.messages,
            return_tensors="pt",
            tokenize=False,
            add_generation_prompt=True,
        )
    except IndexError:
        logger.error("bad messages? '%s'", str(instruct_request.model_dump()))
        raise
    except ValueError:
        if len(instruct_request.messages) > 1:
            prompt_chain = [
                "{role}: {content}".format(
                    role=message.role.value, content=message.content
                )
                for message in instruct_request.messages
            ]
            inputs = "\n".join(prompt_chain)
        elif len(instruct_request.messages) == 1:
            inputs = instruct_request.messages[0].content
        else:
            inputs = [tokenizer.eos_token_id]

        logger.error(
            "failed to use apply_chat_template, manually merged to '%s'", str(inputs)
        )
    except Exception as e:
        logger.exception(
            "failed to parse: '%s' [%s]", str(instruct_request.model_dump()), str(e)
        )
        raise

    logger.debug("templated input: '%s'", str(inputs))
    # inputs = encodeds.to("cpu")

    model_inputs = tokenizer([inputs], return_tensors="pt")
    logger.debug("model_inputs: '%s'", str(model_inputs))
    logger.debug("model_inputs: '%i'", model_inputs.input_ids.nelement())

    # FIXME: we can use model.can_generate to check if it is a sequence generator

    # set the random seed
    if instruct_request.seed:
        set_seed(instruct_request.seed)

    T1 = clock()

    # run inference on the model
    with torch.no_grad():
        # https://huggingface.co/docs/transformers/en/main_classes/text_generation
        model_outputs = model.generate(
            model_inputs.input_ids,
            max_new_tokens=instruct_request.max_tokens,
            pad_token_id=tokenizer.eos_token_id,
            do_sample=False,
            temperature=instruct_request.temperature,
            top_k=1,
            top_p=instruct_request.top_p,
            repetition_penalty=instruct_request.repetition_penalty,
            no_repeat_ngram_size=instruct_request.no_repeat_ngram_size,
        )
    iduration = clock() - T1
    logger.debug("model_outputs: '%s'", str(model_outputs))
    logger.debug("model_outputs: '%s'", str(type(model_outputs)))

    generated_ids = [
        output_ids[len(input_ids) :]
        for input_ids, output_ids in zip(model_inputs.input_ids, model_outputs)
    ]
    logger.debug("generated_ids: '%s'", str(generated_ids))
    logger.debug("generated_ids: '%s'", str(type(generated_ids)))
    logger.debug("generated_ids: '%s'", str([str(type(x)) for x in generated_ids]))

    outputs = tokenizer.batch_decode(generated_ids, skip_special_tokens=True)
    logger.debug("outputs: '%s'", str(outputs))

    input_tokens = model_inputs.input_ids.nelement()
    output_tokens = sum(x.nelement() for x in generated_ids)

    duration = clock() - T

    logger.info(
        "'%s' %i tokens [input=%i, genids=%i] in %0.2fs",
        instruct_request.model,
        input_tokens + output_tokens,
        input_tokens,
        output_tokens,
        duration,
    )

    logger.debug(
        "messages: %s, inputs: %s, genids: %s, outputs: %s",
        str(instruct_request.messages),
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
        model=instruct_request.model,
        choices=[InstructMessage(role=InstructRole.ASSISTANT, content=outputs[0])],
        usage=usage
    )

    update_metrics(user_id, ModelType.INSTRUCT, instruct_request.model, response.usage.model_dump())

    return response


def lambda_handler(event, context):
    """run the data through the model
    TODO: capture the username and request refs in the logs
    """
    logger.info("event: '%s'", str(event))

    try:
        user_id = get_userid_from_event(event)
    except Exception as e:
        logger.error("failed to get user_id from event '%s'", str(event))
        return mk_resp(400, {"status": "error", "message": "missing userid"})

    try:
        data, mimetype = lambda_event_to_data(event, data_key="body")
    except KeyError as e:
        return mk_resp(
            400, {"status": "error", "message": "missing key: '%s'" % str(e)}
        )

    try:
        instruct_request = InstructRequest.model_validate(data)
    except Exception as e:
        logger.error("failed to parse '%s' as InstructRequest [%s]", str(data), str(e))
        return mk_resp(
            400, {"status": "error", "message": "invalid input [%s]" % str(e)}
        )

    # TODO: the model name does not match the user request exactly (usually a prepend missing)
    # if instruct_request.model != MODELNAME:
    #    logger.error(
    #        "routing error for '%s', recieved: '%s'", MODELNAME, str(instruct_request)
    #    )
    #    return {"statusCode": 500, "body": "internal error"}

    logger.info("submitting '%s'", str(instruct_request))

    # do the processing
    try:
        response = instruct_process(user_id, instruct_request)
    except ModelNotFoundError as e:
        logger.error("'%s' not found [%s]", instruct_request.model, str(e))
        return mk_resp(
            404,
            {
                "status": "error",
                "message": "'%s' is not a valid modelname" % instruct_request.model,
            },
        )
    except EmptyMessagesError as e:
        logger.error("empty messages")
        return mk_resp(400, {"status": "error", "message": "empty messages list"})
    except Exception as e:
        logger.exception("unknown error in instruct_process [%s]", str(e))
        return mk_resp(500, {"status": "error", "message": "unknown error"})

    # NB: this response must be a valid lambda apigw response object
    return mk_resp(
        200,
        response.model_dump(),
        isBase64Encoded=False,
    )


def batch_handler():
    """called from batch jobs using the cli"""
    import sys

    user_id = sys.argv[1]
    message_id = sys.argv[2]
    data = json.loads(sys.argv[3])

    try:
        instruct_request = InstructRequest.model_validate(data)
    except Exception as e:
        logger.exception(
            "[%s/%s] failed to parse '%s' as InstructRequest [%s]",
            user_id,
            message_id,
            str(data),
            str(e),
        )
        response = mk_resp(
            500, {"status": "error", "message": "unable to parse request"}
        )
        instruct_request = None

    if instruct_request:
        try:
            response = instruct_process(user_id, instruct_request).model_dump()
        except Exception as e:
            logger.exception(
                "[%s/%s] failed to process request [%s]", user_id, message_id, str(e)
            )
            response = mk_resp(
                500, {"status": "error", "message": "unable to process request"}
            )

    # write the completion data to dynamodb
    results_table = os.environ["RESULTS_TABLE"]

    try:
        update_results_table(user_id, message_id, results_table, response)
    except Exception as e:
        logger.exception(
            "[%s/%s] unable to save results [%s]", user_id, message_id, str(e)
        )
