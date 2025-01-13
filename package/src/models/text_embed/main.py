"""process a sentence to an embedding
"""
import os
import logging
import torch
from sentence_transformers.quantization import quantize_embeddings

from time import perf_counter as clock

from shared import get_userid_from_event, lambda_event_to_data, mk_resp, get_memory_usage, update_metrics

from api.models import EmbedTextRequest, EmbeddingQuantization, EmbedTextResponse, ModelUsageStats, ModelType


LOAD_PACKAGE_T = clock()
from models.cache_model import load_text_embedding

LOAD_PACKAGE_T = clock() - LOAD_PACKAGE_T


logger = logging.getLogger()
logger.setLevel(os.getenv("LOG_LEVEL") or "INFO")

logger.info("import load_text_embedding in %0.2fs", LOAD_PACKAGE_T)


MODELNAME = os.environ["MODELNAME"]


def lambda_handler(event, context):
    """run the data through the model
    FIXME: validate the input is a single string
    TODO: should we handle array of strings?
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
        logger.error("[%s] missing key: '%s'", MODELNAME, str(e))
        # print("[%s] missing key: '%s'" % (MODELNAME, str(e)))
        return mk_resp(400, {"status": "error", "message": "missing key: '%s'" % str(e)})

    logger.debug("[%s] parsed '%s' as '%s'", MODELNAME, str(data), str(mimetype))
    # print("[%s] parsed '%s' as '%s'" % (MODELNAME, str(data), str(mimetype)))

    #    try:
    #        data = json.loads(data)
    #    except Exception as e:
    #        logger.error("[%s] failed to parse '%s' as json [%s]", MODELNAME, str(data), str(e))
    #        #print("[%s] failed to parse '%s' as json [%s]" % (MODELNAME, str(data), str(e)))
    #        return {"status": "error", "statusCode": 400, "message": "'body' is not valid json"}

    try:
        request = EmbedTextRequest.model_validate(data)
    except Exception as e:
        logger.error("failed to parse '%s' as EmbeddingRequest [%s]", str(data), str(e))
        return mk_resp(400, {"status": "error", "message": "invalid input [%s]" % str(e)})

    # validate the input
    if request.model != MODELNAME:
        logger.error("modelname mismatch: expected: '%s' != received: '%s'", MODELNAME, request.model)
        return mk_resp(400, {"status": "error", "message": "modelname mismatch: expected '%s' != received: '%s'" % (MODELNAME, request.model)})

    if not isinstance(request.input, str):
        logger.error("input must be a string [%s]", str(type(request.input)))
        return mk_resp(400, {"status": "error", "message": "body.input must be a string"})

    T = clock()
    logger.info("[%s] loading...", MODELNAME)
    tokenizer, model = load_text_embedding(MODELNAME)
    logger.info("[%s] loaded in %0.2fs", MODELNAME, (clock() - T))

    T = clock()

    # get the number of tokens
    encoded_inputs = tokenizer([request.input], padding=True, truncation=True, return_tensors="pt")
    input_tokens = encoded_inputs.input_ids.nelement()

    try:
        with torch.no_grad():
            embeddings = model.encode(request.input)
    except Exception as e:
        logger.critical("[%s] encoding '%s' failed [%s]", MODELNAME, str(data), str(e))
        return mk_resp(400, {"status": "error", "message": "failed to encode '%s'" % str(data)})

    # logger.info("embeddings: '%s' [%s]", str(embeddings), str(type(embeddings)))
    iduration = clock() - T

    try:
        if request.quantization != EmbeddingQuantization.FLOAT32:
            embeddings = quantize_embeddings(embeddings, precision=request.quantization)
    except Exception as e:
        logger.error("[%s] unable to quantize embeddings to '%s' [%s]", MODELNAME, request.quantization, str(e))
        return mk_resp(500, {"status": "error", "message": "unable to quantize embeddings"})

    # NB: we remove the batch id here, which assumes we have extactly one string in the input.
    try:
        e = embeddings.tolist()
    except Exception as e:
        logger.critical(
            "[%s] listing '%s' [%s] failed [%s]",
            MODELNAME,
            str(embeddings),
            str(type(embeddings)),
            str(e),
        )
        return mk_resp(400, {"status": "error", "message": "failed to convert '%s'" % str(data)})

    PRECISION = 0
    if PRECISION > 0:
        try:
            e = [round(e_, PRECISION) for e_ in e]
        except Exception as ex:
            logger.critical(
                "[%s] snipping '%s' [%s] failed [%s]",
                MODELNAME,
                str(e),
                str(type(e)),
                str(ex),
            )
            # print("[%s] snipping '%s' [%s] failed [%s]" % (MODELNAME, str(e), str(type(e)), str(ex)))
            return mk_resp(400, {"status": "error", "message": "failed to convert '%s'" % str(data)})

    duration = clock() - T
    logger.info("'%s' %i tokens in %0.2fs", MODELNAME, len(embeddings), duration)
    # print("[%s] %i tokens in %0.2fs" % (MODELNAME, len(embeddings), duration))

    response = EmbedTextResponse(
        model=MODELNAME,
        embedding=e,
        usage=ModelUsageStats(
            duration=duration,
            inference=iduration,
            input_tokens=input_tokens,
            output_tokens=0,
            memory_usage=get_memory_usage()
        ),
    )

    update_metrics(user_id, ModelType.TEXT_EMBEDDING, response.model, response.usage.model_dump())

    return mk_resp(200, response.model_dump())
