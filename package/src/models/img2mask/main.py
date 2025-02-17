"""image segmentation

returns mask images a single input image

TODO: this process is ctrl-r from depth masks, parameterize:
+ model_load_fn (load_depth, load_img2mask)
+ request model (DepthRequest, Img2MaskRequest)
+ response model (DepthResponse, Img2MaskResponse)
and generalize
"""
import os
import logging
import io
import torch

from time import perf_counter as clock

from PIL import Image
from base64 import b64encode

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
    Img2MaskRequest,
    Img2MaskResponse,
    ModelUsageStats,
)

LOAD_IMG2MASK_T = clock()
from models.cache_model import load_img2mask, ModelNotFoundError

LOAD_IMG2MASK_T = clock() - LOAD_IMG2MASK_T


logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL") or "INFO")

logger.info("import img2mask in %0.2fs", LOAD_IMG2MASK_T)


def img2mask_process(user_id: str, request: Img2MaskRequest) -> Img2MaskResponse:
    """process a segmentation request
    This method is the base method to be called from all lambda, sfn, batch etc handlers
    """
    T = clock()

    try:
        processor, model = load_img2mask(request.model)
    except ModelNotFoundError as e:
        logger.critical("'%s' failed to load model", request.model)
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

    masks = processor.image_processor.post_process_masks(
        outputs.pred_masks.cpu(),
        inputs["original_sizes"].cpu(),
        inputs["reshaped_input_sizes"].cpu(),
    )
    scores = outputs.iou_scores

    iduration = clock() - T1

    # visualize the prediction
    # FIXME: stack the masks into an rgb, or map to 255 or something
    output = masks.squeeze().cpu().numpy()
    formatted = (output * 255 / output.max()).astype("uint8")
    labels = Image.fromarray(formatted)

    # save the depth to a PIL image in the buffer
    with io.BytesIO() as f:
        # FIXME: take output format from the request
        labels.save(f, format="PNG")
        f.seek(0)
        labels_b64 = b64encode(f.getvalue())

    duration = clock() - T

    logger.info("'%s' in %0.2fs", request.model, duration)

    usage = ModelUsageStats(
        duration=duration,
        inference=iduration,
        input_tokens=0,
        output_tokens=0,
        memory_usage=get_memory_usage(),
    )

    response = Img2MaskResponse(
        model=request.model,
        labels=labels_b64,
        scores=scores,
        usage=usage,
    )

    # send the usage to the quue
    update_metrics(
        user_id, ModelType.IMAGE_MASK, request.model, response.usage.model_dump()
    )

    return response


def lambda_handler(event, context):
    """run the data through the model
    TODO: capture the username and request refs in the logs
    """
    logger.debug("event: '%s'", str(event))

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
        request = Img2MaskRequest.model_validate(data)
    except Exception as e:
        logger.error("failed to parse '%s' as InstructRequest [%s]", str(data), str(e))
        return mk_resp(
            400, {"status": "error", "message": "invalid input [%s]" % str(e)}
        )

    logger.info("submitting '%s'", str(request))

    # do the processing
    try:
        response = img2mask_process(user_id, request)
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
        response.model_dump(),
        isBase64Encoded=False,
    )
