"""Output persistence.

Writes inference results to S3 (binary outputs) and DynamoDB (status and
JSON results). Also provides image decoding and encoding utilities used by
image-input handlers.
"""

import io
import json
import logging
import os
from base64 import b64decode

import boto3
from botocore.exceptions import ClientError, NoRegionError
from dynawrap.backends.dynamodb import DynamoDBBackend
from PIL import Image

from shared.enums import ModelType
from shared.models import OutputReference
from shared.db_models import ResultsItem


logger = logging.getLogger(__name__)

try:
    _s3 = boto3.client("s3")
    _ddb = boto3.client("dynamodb")
    _dynawrap = DynamoDBBackend(_ddb)
except NoRegionError:
    logger.warning("aws unavailable")
    _s3 = None
    _ddb = None
    _dynawrap = None


# ---------------------------------------------------------------------------
# Image utilities
# ---------------------------------------------------------------------------


def decode_image(b64_str: str) -> Image.Image:
    """Decode a base64 image string to a PIL Image.

    Accepts raw base64 or a data-URI prefix (data:image/jpeg;base64,...).
    For http/https URLs delegates to transformers.image_utils.load_image.
    """
    if b64_str.startswith(("http://", "https://")):
        from transformers.image_utils import load_image
        return load_image(b64_str)
    if b64_str.startswith("data:"):
        b64_str = b64_str.split(",", 1)[1]
    return Image.open(io.BytesIO(b64decode(b64_str))).convert("RGB")


def image_to_png_bytes(image: Image.Image) -> bytes:
    """Encode a PIL Image to PNG bytes."""
    with io.BytesIO() as buf:
        image.save(buf, format="PNG")
        return buf.getvalue()


# ---------------------------------------------------------------------------
# S3
# ---------------------------------------------------------------------------


def write_binary_output(
    message_id: str,
    model_type: ModelType,
    field_name: str,
    data: bytes,
    mimetype: str,
    bucket: str,
) -> "OutputReference":
    """Write binary model output to S3 and return an OutputReference.

    Key schema: outputs/{model_type}/{message_id}/{field_name}

    :param message_id: unique identifier for this inference request
    :param model_type: ModelType enum value, used as the S3 key prefix
    :param field_name: name of the output field, e.g. "audio", "image"
    :param data:       raw binary content to store
    :param mimetype:   MIME type of the content, stored as S3 ContentType
    :param bucket:     name of the S3 output bucket
    :returns:          OutputReference with key and mimetype
    """
    key = "outputs/%s/%s/%s" % (model_type.value, message_id, field_name)

    try:
        _s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=data,
            ContentType=mimetype,
        )
        logger.info("wrote %ib to s3://%s/%s", len(data), bucket, key)
    except Exception as e:
        logger.exception(
            "failed to write output to s3://%s/%s [%s]", bucket, key, str(e)
        )
        raise

    return OutputReference(path=key, mimetype=mimetype)


# ---------------------------------------------------------------------------
# DynamoDB
# ---------------------------------------------------------------------------


def update_results_table(
    user_id: str,
    message_id: str,
    response: dict,
    status: str = "complete",
):
    """Write a result or status update to the results cache table."""
    results_table = os.getenv("DYNAMODB_RESULTS_TABLE")

    if not results_table:
        logger.warning(
            "[%s/%s] DYNAMODB_TABLE not set, skipping results write",
            user_id,
            message_id,
        )
        return

    item = ResultsItem(
        user_id=user_id,
        message_id=message_id,
        status=status,
        response=json.dumps(response) if response is not None else None,
    )

    try:
        _dynawrap.save(results_table, item)
        logger.info(
            "[%s/%s] status='%s' written to dynamodb",
            user_id,
            message_id,
            status,
        )
    except ClientError as e:
        logger.critical(
            "[%s/%s] failed to write to dynamodb table '%s' [%s]",
            user_id,
            message_id,
            results_table,
            str(e),
        )
