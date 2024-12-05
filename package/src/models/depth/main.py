"""monocular depth estimation

returns an estimated depth image for a single input image
"""
import os
import logging
import io
import torch

from time import perf_counter as clock

from PIL import Image
from base64 import b64encode

from shared import lambda_event_to_data, mk_resp, update_results_table, get_memory_usage
from api.models import (
    DepthRequest,
    DepthResponse,
    ModelUsageStats,
)

LOAD_DEPTH_T = clock()
from models.cache_model import load_depth, ModelNotFoundError

LOAD_DEPTH_T = clock() - LOAD_DEPTH_T


logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL") or "INFO")

logger.info("import load_depth in %0.2fs", LOAD_DEPTH_T)


def depth_process(request: DepthRequest) -> DepthResponse:
    """process a depth request
    This method is the base method to be called from all lambda, sfn, batch etc handlers
    """
    T = clock()

    try:
        processor, model = load_depth(request.model)
    except ModelNotFoundError as e:
        logger.critical("'%s' failed to load tokenizer", request.model)
        raise e

    logger.info("'%s' loaded in %0.2fs", request.model, (clock() - T))

    T = clock()
    # FIXME: parse the image in the request (should be base64)
    image = None

    # prepare image for the model
    inputs = processor(images=image, return_tensors="pt")
    logger.debug("model_inputs: '%s'", str(inputs))
    logger.debug("model_inputs: '%i'", inputs.input_ids.nelement())

    T1 = clock()

    with torch.no_grad():
        outputs = model(**inputs)
        predicted_depth = outputs.predicted_depth

    # TODO: offload this to the client
    # interpolate to original size
    prediction = torch.nn.functional.interpolate(
        predicted_depth.unsqueeze(1),
        size=image.size[::-1],
        mode="bicubic",
        align_corners=False,
    )

    iduration = clock() - T1

    # visualize the prediction
    output = prediction.squeeze().cpu().numpy()
    formatted = (output * 255 / output.max()).astype("uint8")
    depth = Image.fromarray(formatted)

    # save the depth to a PIL image in the buffer
    with io.BytesIO() as f:
        # FIXME: take output format from the request
        depth.save(f, format="JPEG")
        f.seek(0)
        depth_b64 = b64encode(f.getvalue())

    duration = clock() - T

    logger.info("'%s' in %0.2fs", request.model, duration)

    response = DepthResponse(
        model=request.model,
        image=depth_b64,
        usage=ModelUsageStats(
            duration=duration,
            inference=iduration,
            input_tokens=0,
            output_tokens=0,
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
        request = DepthRequest.model_validate(data)
    except Exception as e:
        logger.error("failed to parse '%s' as InstructRequest [%s]", str(data), str(e))
        return mk_resp(
            400, {"status": "error", "message": "invalid input [%s]" % str(e)}
        )

    logger.info("submitting '%s'", str(request))

    # do the processing
    try:
        response = depth_process(request).model_dump()
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
        logger.exception("unknown error in instruct_process [%s]", str(e))
        return mk_resp(500, {"status": "error", "message": "unknown error"})

    # NB: this response must be a valid lambda apigw response object
    return mk_resp(
        200,
        response,
        headers={"Content-Type": "application/json"},
        isBase64Encoded=False,
    )
