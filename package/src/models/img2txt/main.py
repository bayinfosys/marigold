"""image to text model

for OCR, text extraction, image labelling/description, and VQA
"""
import os
import logging
import torch
import io

from base64 import b64encode, b64decode

from PIL import Image
from time import perf_counter as clock

from transformers import set_seed
from transformers.image_utils import load_image

from shared import lambda_event_to_data, mk_resp, update_results_table, get_memory_usage

from api.models import (
    InstructRole,
    InstructMessage,
    InstructMessageContentList,
    InstructMessageTextContent,
    InstructMessageImageContent,
    InstructMessageContentType,
    InstructMessageContentHF,
    InstructRequest,
    Img2TxtResponse,
    ModelUsageStats,
)

LOAD_INSTRUCT_T = clock()
from models.cache_model import load_img2txt, ModelNotFoundError

LOAD_INSTRUCT_T = clock() - LOAD_INSTRUCT_T


logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL") or "INFO")

logger.info("import load_img2txt in %0.2fs", LOAD_INSTRUCT_T)


def verify_image(img):
    img.verify()


def load_image_from_b64(image_str: str) -> Image.Image:
    """Load the image from base64 representation using the hf library."""
    img = load_image(image_str)
    logger.info("read %ib as image '%s.%s'", len(image_str), img.size, str(img.mode))
    return img


def save_image_to_b64(image: Image.Image) -> str:
    """Save the image to a base64 string using Pillow."""
    with io.BytesIO() as buffer:
        image.save(buffer, format="PNG")  # Ensure the format is specified
        b64_str = b64encode(buffer.getvalue()).decode("utf-8")
    return b64_str


# Define a chat history and use `apply_chat_template` to get formatted prompt
# Each entry has to be a list of dicts with types ("text", "image")
# TODO: InstructMessage.content is a string, but this type is an array.
#       create function which takes an InstructMessage and returns this.
DEFAULT_CONVERSATION = [
    {
        "role": "user",
        "content": [
            {"type": "image"},
            {"type": "text", "text": "Can you describe this image?"},
        ],
    },
]


def img2txt_process(request: InstructRequest) -> Img2TxtResponse:
    """process a request"""
    try:
        tokenizer, model = load_img2txt(request.model)
    except ModelNotFoundError as e:
        logger.critical("'%s' failed to load tokenizer", request.model)
        raise e

    # load images from the request base64
    images = []
    for idx, message_content in enumerate(
        [
            msg
            for x in request.messages
            if isinstance(x.content, list)
            for msg in x.content
        ]
    ):
        logger.info("[%03i] message_content: '%s'", idx, str(message_content))

        if isinstance(message_content, InstructMessageImageContent):
            try:
                images.append(load_image_from_b64(message_content.image))
            except Exception as e:
                logger.exception("unable to parse image [%s]", str(e))
        else:
            logger.info("[%03i] not image content [%s]", idx, str(message_content))

    logger.info("%i images found", len(images))

    if not images:
        raise

    # translate the prompt to huggingface format
    # NB: we serialize this to dict, so type checking is a little patchy.
    logger.info("promtp: %s", str(request.messages))

    hf_prompt = []
    for message in request.messages:
        if isinstance(message.content, str):
            hf_prompt.append(
                InstructMessage(role=message.role, content=message.content).model_dump()
            )
        elif isinstance(message.content, list):
            cont = []
            for mc in message.content:
                if isinstance(mc, InstructMessageTextContent):
                    cont.append(
                        InstructMessageContentHF(
                            type=InstructMessageContentType.TEXT, text=mc.text
                        )
                    )
                elif isinstance(mc, InstructMessageImageContent):
                    cont.append(
                        InstructMessageContentHF(type=InstructMessageContentType.IMAGE)
                    )
                else:
                    logger.error(
                        "unhandled message content type: '%s' [%s]",
                        str(type(mc)),
                        str(mc),
                    )
                    raise

            hf_prompt.append(
                {
                    "role": message.role,
                    "content": [x.model_dump(by_alias=True) for x in cont],
                }
            )

    T = clock()

    logger.info("tokenzing prompt: '%s'", str(hf_prompt))

    try:
        prompt = tokenizer.apply_chat_template(
            hf_prompt,
            return_tensors="pt",
            tokenize=False,
            add_generation_prompt=True,
        )
    except Exception as e:
        logger.exception(
            "failed to parse: '%s' [%s]", str(request.model_dump()), str(e)
        )
        raise

    logger.debug("templated input: '%s'", str(prompt))
    # inputs = encodeds.to("cpu")

    model_inputs = tokenizer(text=prompt, images=images, return_tensors="pt")
    logger.debug("model_inputs: '%s'", str(model_inputs))
    logger.debug("model_inputs: '%i'", model_inputs.input_ids.nelement())

    #
    # INFERENCE
    #
    if request.seed:
        set_seed(request.seed)

    T1 = clock()

    with torch.no_grad():
        model_outputs = model.generate(
            **model_inputs, max_new_tokens=request.max_tokens
        )

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
    # generated_ids = model_outputs
    logger.debug("gen_ids: '%s'", str(generated_ids))
    logger.debug("gen_ids.type: '%s'", str(type(generated_ids)))
    logger.debug("gen_ids[].type: '%s'", str([str(type(x)) for x in generated_ids]))

    outputs = tokenizer.batch_decode(generated_ids, skip_special_tokens=True)
    logger.debug("decoded-outputs: '%s'", str(outputs))

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
        "messages: %s, prompt: %s, genids: %s, outputs: %s",
        str(request.messages),
        str(prompt),
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
            memory_usage=get_memory_usage(),
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
        request = InstructRequest.model_validate(data)
    except Exception as e:
        logger.error("failed to parse '%s' as InstructRequest [%s]", str(data), str(e))
        return mk_resp(
            400, {"status": "error", "message": "invalid input [%s]" % str(e)}
        )

    logger.debug("submitting '%s'", str(request))

    # do the processing
    try:
        response = img2txt_process(request).model_dump()
    except ModelNotFoundError as e:
        logger.error("'%s' not found [%s]", request.model, str(e))
        return mk_resp(
            404,
            {
                "status": "error",
                "message": "'%s' is not a valid modelname" % request.model,
            },
        )
    except Exception as e:
        logger.exception("unknown error in img2txt_process [%s]", str(e))
        return mk_resp(500, {"status": "error", "message": "unknown error"})

    # NB: this response must be a valid lambda apigw response object
    return mk_resp(
        200,
        response,
        headers={"Content-Type": "application/json"},
        isBase64Encoded=False,
    )
