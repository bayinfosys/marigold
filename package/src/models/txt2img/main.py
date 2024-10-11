"""image from text model

{"input": "picture of a cat please"}

returns image as base64 string
"""
import os
import logging
import base64
import torch
import io

import numpy as np

from time import perf_counter as clock
from PIL import Image

from diffusers import DiffusionPipeline

from shared import lambda_event_to_data
from models.cache_model import load_txt2img


logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL") or "INFO")


MODELNAME = os.environ["MODELNAME"]
NUM_STEPS = int(os.getenv("NUM_STEPS") or 10)

T = clock()
pipe = load_txt2img(MODELNAME)
logger.info("'%s' loaded in '%0.2fs", MODELNAME, (clock() - T))


def validate_input(data):
    if not isinstance(data, str):
        raise ValueError("data must be dict")


def lambda_handler(event, context):
    """run the data through the model"""
    try:
        data, mimetype = lambda_event_to_data(event)
    except KeyError as e:
        return {
            "status": "error",
            "status_code": 400,
            "message": "missing key: '%s'" % str(e),
        }

    logger.info("reading '%s' '%s'", str(data), mimetype)

    try:
        validate_input(data)
    except Exception as e:
        return {
            "status": "error",
            "status_code": 400,
            "message": "invalid input [%s]" % str(e),
        }

    prompt = data

    logger.debug("submitting '%s'", str(prompt))

    T = clock()

    image = pipe(
        prompt=prompt,
        num_inference_steps=NUM_STEPS,
        output_type="np",
        guidance_scale=0.0,
    ).images[0]

    duration = clock() - T

    logger.info(
        "'%s' %s.%s [%0.2f->%0.2f] in %0.2fs",
        MODELNAME,
        str(image.shape),
        str(image.dtype),
        image.min(),
        image.max(),
        duration,
    )

    with io.BytesIO() as output:
        img = Image.fromarray(np.uint8(image * 255.0))
        img.save(output, format="PNG")
        contents = output.getvalue()

    encoded = base64.b64encode(contents)

    logger.info("%ib encoded to %ib", len(contents), len(encoded))

    return {
        "headers": {"Content-Type": "image/png"},
        "statusCode": 200,
        "body": encoded,
        "isBase64Encoded": True,
        "stats": {"duration": duration},
    }
