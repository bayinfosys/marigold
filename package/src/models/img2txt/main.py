"""image to text model

for OCR, text extraction, image labelling/description, and VQA
"""
import os
import logging
import imageio
import torch

from PIL import Image
from time import perf_counter as clock

from transformers import set_seed

from shared import lambda_event_to_data, mk_resp, update_results_table
from api.models import (
    InstructRole,
    InstructMessage,
    Img2TxtRequest,
    Img2TxtResponse,
    ModelUsageStats
)

LOAD_INSTRUCT_T = clock()
from models.cache_model import load_img2txt, ModelNotFoundError

LOAD_INSTRUCT_T = clock() - LOAD_INSTRUCT_T


logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL") or "INFO")

logger.info("import load_img2txt in %0.2fs", LOAD_INSTRUCT_T)


def load_image_from_b64(image_str: str):
    """load the image from b64 representation"""
    from io import BytesIO
    from base64 import b64decode

    with BytesIO(b64decode(image_str)) as f:
        img = imageio.imread(f)

    logger.info("read %ib as '%s'", len(image_str), str(img.shape))
    return img


def save_image_to_b64(image: Image):
    """save the image from binary to b64"""
    pass


# Define a chat history and use `apply_chat_template` to get formatted prompt
# Each entry has to be a list of dicts with types ("text", "image")
# TODO: InstructMessage.content is a string, but this type is an array.
#       create function which takes an InstructMessage and returns this.
DEFAULT_CONVERSATION = [
    {
      "role": "user",
      "content": [
          {"type": "text", "text": "Describe this image."},
          {"type": "image"},
        ],
    },
]


def chat_template_naver_clova_ix_donut_base_finetuned_docvqa(chat, t, m, image):
    import re

    task_prompt = "<s_docvqa><s_question>{user_input}</s_question><s_answer>"
    question = "What is in the picture?"
    prompt = task_prompt.replace("{user_input}", question)

    decoder_input_ids = t.tokenizer(prompt, add_special_tokens=False, return_tensors="pt").input_ids

    pixel_values = t(image, return_tensors="pt").pixel_values

    outputs = m.generate(
        pixel_values,
        decoder_input_ids=decoder_input_ids,
        max_length=m.decoder.config.max_position_embeddings,
        pad_token_id=t.tokenizer.pad_token_id,
        eos_token_id=t.tokenizer.eos_token_id,
        use_cache=True,
        bad_words_ids=[[t.tokenizer.unk_token_id]],
        return_dict_in_generate=True,
    )

    sequence = t.batch_decode(outputs.sequences)[0]

    sequence = sequence.replace(t.tokenizer.eos_token, "").replace(t.tokenizer.pad_token, "")
    print(sequence)


def img2txt_process(request: Img2TxtRequest) -> Img2TxtResponse:
    """process a request"""
    T = clock()

    try:
        tokenizer, model = load_img2txt(request.model)
    except ModelNotFoundError as e:
        logger.critical("'%s' failed to load tokenizer", request.model)
        raise e

    logger.info("'%s' loaded in %0.2fs", request.model, (clock() - T))

    T = clock()

    # FIXME: load the model from the request base64
    images = [load_image_from_b64(image_str) for image_str in request.images]

    T = clock()
    try:
        inputs = tokenizer.apply_chat_template(
            DEFAULT_CONVERSATION,
            return_tensors="pt",
            tokenize=False,
            add_generation_prompt=True,
        )
    except ValueError:
        logger.error("failed to use apply_chat_template")
        model_outputs = chat_template_naver_clova_ix_donut_base_finetuned_docvqa(None, tokenizer, model, images[0])
    except Exception as e:
        logger.exception("failed to parse: '%s' [%s]", str(request.model_dump()), str(e))
        raise

    logger.debug("templated input: '%s'", str(inputs))
    # inputs = encodeds.to("cpu")

    model_inputs = tokenizer(images=images[0], text=inputs, return_tensors="pt")
    logger.debug("model_inputs: '%s'", str(model_inputs))
    logger.debug("model_inputs: '%i'", model_inputs.input_ids.nelement())

    #
    # INFERENCE
    #
    if request.seed:
        set_seed(request.seed)

    T1 = clock()

    with torch.no_grad():
        model_outputs = model.generate(model_inputs.input_ids, max_new_tokens=request.max_tokens, do_sample=False)

    iduration = clock() - T1
    logger.debug("model_outputs: '%s'", str(model_outputs))
    logger.debug("model_outputs: '%s'", str(type(model_outputs)))

    #
    # DECODE OUTPUTS
    #
    generated_ids = [
        output_ids[len(input_ids) :]
        for input_ids, output_ids in zip(model_inputs.input_ids, model_outputs)
    ]
    logger.debug("generated_ids: '%s'", str(generated_ids))
    logger.debug("generated_ids: '%s'", str(type(generated_ids)))
    logger.debug("generated_ids: '%s'", str([str(type(x)) for x in generated_ids]))

    outputs = tokenizer.batch_decode(generated_ids, skip_special_tokens=True)
    logger.debug("outputs: '%s'", str(outputs))

    duration = clock() - T

    input_tokens = model_inputs.input_ids.nelement()
    output_tokens = sum(x.nelement() for x in generated_ids)

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

    response = Img2TxtResponse(
        model=request.model,
        choices=[InstructMessage(role=InstructRole.ASSISTANT, content=outputs[0])],
        usage=ModelUsageStats(
            duration=duration,
            inference=iduration,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        ),
    )

    return response


def lambda_handler(event, context):
    """run the data through the model
    TODO: capture the username and request refs in the logs
    """
    logger.debug("event: '%s'", str(event))

    try:
        data, mimetype = lambda_event_to_data(event, data_key="body")
    except KeyError as e:
        return mk_resp(
            400, {"status": "error", "message": "missing key: '%s'" % str(e)}
        )

    try:
        request = Img2TxtRequest.model_validate(data)
    except Exception as e:
        logger.error("failed to parse '%s' as Img2TxtRequest [%s]", str(data), str(e))
        return mk_resp(
            400, {"status": "error", "message": "invalid input [%s]" % str(e)}
        )

    # TODO: the model name does not match the user request exactly (usually a prepend missing)
    # if instruct_request.model != MODELNAME:
    #    logger.error(
    #        "routing error for '%s', recieved: '%s'", MODELNAME, str(instruct_request)
    #    )
    #    return {"statusCode": 500, "body": "internal error"}

    logger.info("submitting '%s'", str(request))

    # do the processing
    try:
        response = img2txt_process(request).model_dump()
    except ModelNotFoundError as e:
        logger.error("'%s' not found [%s]", request.model, str(e))
        return mk_resp(404, {"status": "error", "message": "'%s' is not a valid modelname" % request.model})
    except Exception as e:
        logger.exception("unknown error in img2txt_process [%s]", str(e))
        return mk_resp(500, {"status": "error", "message": "unknown error"})

    # NB: this response must be a valid lambda apigw response object
    return mk_resp(200, response, headers={"Content-Type": "application/json"}, isBase64Encoded=False)
