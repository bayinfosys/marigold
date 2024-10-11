"""process a sentence to an embedding
"""
import os
import logging

from time import perf_counter as clock

from shared import lambda_event_to_data, mk_resp

from api.models import EmbedTextResponse, ModelUsageStats


LOAD_PACKAGE_T = clock()
from models.cache_model import load_text_embedding

LOAD_PACKAGE_T = clock() - LOAD_PACKAGE_T


logger = logging.getLogger()
logger.setLevel(os.getenv("LOG_LEVEL") or "INFO")

logger.info("import load_text_embedding in %0.2fs", LOAD_PACKAGE_T)


MODELNAME = os.environ["MODELNAME"]


T = clock()
model = load_text_embedding(MODELNAME)
logger.info("'%s' loaded in %0.2fs", MODELNAME, (clock() - T))


def lambda_handler(event, context):
    """run the data through the model
    TODO: validate the input is a single string (should we handle array of strings?)
    """
    logger.debug("event: '%s'", str(event))

    try:
        data, mimetype = lambda_event_to_data(event, data_key="body")
    except KeyError as e:
        logger.error("[%s] missing key: '%s'", MODELNAME, str(e))
        # print("[%s] missing key: '%s'" % (MODELNAME, str(e)))
        return mk_resp(
            400, {"status": "error", "message": "missing key: '%s'" % str(e)}
        )

    logger.debug("[%s] parsed '%s' as '%s'", MODELNAME, str(data), str(mimetype))
    # print("[%s] parsed '%s' as '%s'" % (MODELNAME, str(data), str(mimetype)))

    #    try:
    #        data = json.loads(data)
    #    except Exception as e:
    #        logger.error("[%s] failed to parse '%s' as json [%s]", MODELNAME, str(data), str(e))
    #        #print("[%s] failed to parse '%s' as json [%s]" % (MODELNAME, str(data), str(e)))
    #        return {"status": "error", "statusCode": 400, "message": "'body' is not valid json"}

    # load the data
    try:
        modelname = data["model"]
    except KeyError as e:
        logger.error(
            "[%s] '%s' not found in '%s'", MODELNAME, str(e), str(list(data.keys()))
        )
        # print("[%s] '%s' not found in '%s'" % (MODELNAME, str(e), str(list(data.keys()))))
        return mk_resp(400, {"status": "error", "message": "missing 'model' key"})

    try:
        input = data["input"]
    except KeyError as e:
        logger.error(
            "[%s] '%s' not found in '%s'", MODELNAME, str(e), str(list(data.keys()))
        )
        # print("[%s] '%s' not found in '%s'" % (MODELNAME, str(e), str(list(data.keys()))))
        return mk_resp(400, {"status": "error", "message": "missing 'input' key"})

    if modelname != MODELNAME:
        logger.error(
            "modelname mismatch: expected: '%s' != received: '%s'", MODELNAME, modelname
        )
        return mk_resp(
            400,
            {
                "status": "error",
                "message": "modelname mismatch: expected '%s' != received: '%s'"
                % (MODELNAME, modelname),
            },
        )

    if not isinstance(input, str):
        logger.error("input must be a string [%s]", str(type(input)))
        return mk_resp(
            400, {"status": "error", "message": "body.input must be a string"}
        )

    T = clock()

    try:
        embeddings = model.encode(input)
    except Exception as e:
        logger.critical("[%s] encoding '%s' failed [%s]", MODELNAME, str(data), str(e))
        # print("[%s] encoding '%s' failed [%s]" % (MODELNAME, str(data), str(e)))
        return mk_resp(
            400, {"status": "error", "message": "failed to encode '%s'" % str(data)}
        )

    # logger.info("embeddings: '%s' [%s]", str(embeddings), str(type(embeddings)))

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
        # print("[%s] listing '%s' [%s] failed [%s]" % (MODELNAME, str(embeddings), str(type(embeddings)), str(e)))
        return mk_resp(
            400, {"status": "error", "message": "failed to convert '%s'" % str(data)}
        )

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
            return mk_resp(
                400,
                {"status": "error", "message": "failed to convert '%s'" % str(data)},
            )

    duration = clock() - T
    logger.info("'%s' %i tokens in %0.2fs", MODELNAME, len(embeddings), duration)
    # print("[%s] %i tokens in %0.2fs" % (MODELNAME, len(embeddings), duration))

    response = EmbedTextResponse(
        model=MODELNAME,
        embedding=e,
        usage=ModelUsageStats(
            duration=duration,
            inference=0.0,
            input_tokens=0,
            output_tokens=0,
        ),
    )

    return mk_resp(
        200, response.model_dump(), headers={"Content-Type": "application/json"}
    )
