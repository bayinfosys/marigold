"""process an image to an embedding

returns a single vector for a single image input
"""
import os
import logging
import imageio

from time import perf_counter as clock

from shared import lambda_event_to_data

from transformers import AutoImageProcessor, AutoModel


logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL") or "INFO")

MODELNAME = os.environ["MODELNAME"]
PRECISION = os.getenv("PRECISION", 3)

T = clock()

processor = AutoImageProcessor.from_pretrained(MODELNAME, cache_dir="/models")
model = AutoModel.from_pretrained(MODELNAME, cache_dir="/models")
logger.info("'%s' loaded in %0.2fs", MODELNAME, (clock() - T))


def mimetype_to_format(mimetype: str):
    return mimetype.split("/")[-1].upper()


def lambda_handler(event, context):
    """run the data through the model"""
    try:
        data, mimetype = lambda_event_to_data(event)
    except KeyError as e:
        logger.exception(e)
        return {
            "status": "error",
            "status_code": 400,
            "message": "missing key: '%s'" % str(e),
        }
    except Exception as e:
        logger.exception(e)
        return {
            "status": "error",
            "status_code": 400,
            "message": "cannot decode input: '%s'" % str(e),
        }

    # extract the format from the mimetype
    fmt = mimetype_to_format(mimetype)
    logger.info("parsing %i bytes as '%s' [%s]", len(data), fmt, str(type(data)))

    try:
        img = imageio.imread(data, format=fmt)
    except Exception as e:
        logger.exception("'%s' could not parse image as '%s'", str(e), fmt)
        raise e

    logger.info("'%s' read img: [%s]", MODELNAME, (img.shape))

    T = clock()
    input = processor(images=img, return_tensors="pt")
    logger.debug(
        "'%s': input: '%s' [%s]", MODELNAME, str(type(input)), str(input.keys())
    )
    embeddings = model(**input).last_hidden_state[:, 0].cpu()

    logger.info(
        "'%s': emb: '%s' [%s]", MODELNAME, str(type(embeddings)), str(embeddings.shape)
    )

    try:
        e = embeddings[0, :].tolist()
    except Exception as e:
        logger.exception(
            "'%s' could not convert embeddings to list '%s'", MODELNAME, str(e)
        )
        raise e

    logger.debug("'%s': output: '%s' [%s]", MODELNAME, str(type(e)), str(e))

    if PRECISION > 0:
        e = [[round(e_, PRECISION) for e_ in e]]

    logger.info("'%s' %i tokens in %0.2fs", MODELNAME, len(embeddings), (clock() - T))

    return e
