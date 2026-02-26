"""image from text model

{"input": "picture of a cat please"}

returns S3 reference to the generated image
"""
import os
import logging
import torch
import io

import numpy as np

from time import perf_counter as clock
from PIL import Image

from diffusers import DiffusionPipeline

from shared import lambda_event_to_data, mk_resp, get_memory_usage, write_binary_output
from api.models import ModelType, ModelUsageStats, OutputReference, Txt2ImgResponse
from models.cache_model import load_txt2img


logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL") or "INFO")


MODELNAME = os.environ["MODELNAME"]
NUM_STEPS = int(os.getenv("NUM_STEPS") or 10)
OUTPUT_BUCKET = os.environ["OUTPUT_BUCKET"]

T = clock()
pipe = load_txt2img(MODELNAME)
logger.info("'%s' loaded in '%0.2fs", MODELNAME, (clock() - T))


def validate_input(data):
    if not isinstance(data, str):
        raise ValueError("data must be a string prompt")


def lambda_handler(event, context):
    try:
        data, mimetype = lambda_event_to_data(event)
    except KeyError as e:
        return mk_resp(400, {"status": "error", "message": "missing key: '%s'" % str(e)})

    # NB: message_id is passed in the event by the polling lambda
    message_id = event.get("message_id")
    if not message_id:
        return mk_resp(400, {"status": "error", "message": "message_id required"})

    logger.info("reading '%s' '%s'", str(data), mimetype)

    try:
        validate_input(data)
    except Exception as e:
        return mk_resp(400, {"status": "error", "message": "invalid input [%s]" % str(e)})

    prompt = data

    logger.debug("submitting '%s'", str(prompt))

    T = clock()

    image = pipe(
        prompt=prompt,
        num_inference_steps=NUM_STEPS,
        output_type="np",
        guidance_scale=0.0,
    ).images[0]

    iduration = clock() - T

    logger.info(
        "'%s' %s.%s [%0.2f->%0.2f] in %0.2fs",
        MODELNAME, str(image.shape), str(image.dtype),
        image.min(), image.max(), iduration,
    )

    with io.BytesIO() as output:
        img = Image.fromarray(np.uint8(image * 255.0))
        img.save(output, format="PNG")
        image_bytes = output.getvalue()

    image_mimetype = "image/png"
    duration = clock() - T

    image_key = write_binary_output(
        message_id=message_id,
        model_type=ModelType.IMAGE_GEN,
        field_name="image",
        data=image_bytes,
        mimetype=image_mimetype,
        bucket=OUTPUT_BUCKET,
    )

    usage = ModelUsageStats(
        duration=duration,
        inference=iduration,
        input_tokens=0,
        output_tokens=0,
        memory_usage=get_memory_usage(),
    )

    response = Txt2ImgResponse(
        model=MODELNAME,
        usage=usage,
        outputs={
            "image": OutputReference(path=image_key, mimetype=image_mimetype),
        },
    )

    return mk_resp(200, response.model_dump(), isBase64Encoded=False)
