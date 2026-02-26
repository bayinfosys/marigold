"""shared functions usable by all models
+ lambda base64 decoder
"""

import base64
import io
import json
import logging
import os
from base64 import b64decode
from datetime import datetime

import boto3
from api.enums import ModelType
from api.models import ModelUsageStats, OutputReference
from botocore.exceptions import ClientError
from PIL import Image

logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL") or "INFO")


DEFAULT_MIMETYPE = "text/plain"
APPEND_CORS_HEADERS = os.getenv("APPEND_CORS_HEADERS", "False").lower() in (
    "true",
    "1",
    "t",
)


def get_userid_from_event(event):
    """extract a username from an event

    The custom authorizer will relate apikey, jwts, etc to user/group names.
    Here, we access that custom identifier to ensure users access the same data
    regardless of the access method.

    TODO: check specific access method permissions (apikey perms, etc)
    """
    dummy_username = "dummy"

    if "requestContext" in event:
        try:
            return event["requestContext"]["authorizer"]["email"]
        except KeyError:
            logger.error(
                "requestContext.authorizer.email not found in '%s'", str(event)
            )
    elif "destination" in event:  # for step function pipelines
        try:
            return event["destination"]["userid"]
        except KeyError:
            logger.error("destination.userid not found in '%s'", str(event))
    else:
        logger.error(
            "requestContext and destination missing from event '%s'", str(event)
        )

    return dummy_username


def get_path_from_event(event):
    """extract the endpoint path from the lambda event

    NB: various paths exist in the event, some with patterns resolved
    some without, etc. This function returns the path which matches
    the definition given in the openapi spec.
    """
    event_path = " ".join((event["httpMethod"], event["resource"]))

    assert event_path.split(" ")[0] in ("OPTIONS", "GET", "POST", "DELETE")

    return event_path


def path_handler(path, registry):
    """Decorator to register a function as a handler for a given path."""

    def decorator(func):
        registry[path] = func
        return func

    return decorator


def get_memory_usage():
    """return the memory used by the process in MB"""
    import resource

    return 1 + int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0)


def write_binary_output(
    message_id: str,
    model_type: ModelType,
    field_name: str,
    data: bytes,
    mimetype: str,
    bucket: str,
) -> OutputReference:
    """Write binary model output to S3 and return the object key.

    Key schema: outputs/{model_type}/{message_id}/{field_name}

    The returned key is stored in DynamoDB as part of the response, allowing
    the polling endpoint to return a reference the client can fetch via the
    /output/{message_id}/{field_name} API route.

    :param message_id: unique identifier for this inference request
    :param model_type: ModelType enum value, used as the top-level prefix
    :param field_name: name of the output field, e.g. "audio", "image"
    :param data: raw binary content to store
    :param mimetype: MIME type of the content, stored as S3 ContentType
    :param bucket: name of the S3 output bucket
    :returns: OutputReference containing the key and mimetype of the stored binary
    """
    s3_client = boto3.client("s3")
    key = f"outputs/{model_type.value}/{message_id}/{field_name}"

    try:
        s3_client.put_object(
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


def lambda_event_to_data(event, data_key: str = None):
    """extract image/text data from the apigw integration

    NB: this is somewhat hacked, we don't have a way to reliably
        get the mimetype of the binary content from the event, so
        we rely on the user to encode correctly
    """
    data_key_ = data_key or "input"
    mimetype = None

    if event.get("isBase64Encoded"):
        b64_str = event["body"]

        if not b64_str:
            raise ValueError("empty body [%s, %s]" % (str(event), str(type(b64_str))))

        if b64_str.startswith("data:"):
            mimetype, b64_str = b64_str[5:].split(",")
            mimetype = mimetype.split(";")[0]

        try:
            data = base64.b64decode(b64_str)
        except Exception as e:
            logger.exception("unable to decode base64 string [%s]", str(e))
            raise e
    elif isinstance(event[data_key_], str):
        try:
            data = json.loads(event[data_key_])
        except KeyError as e:
            logger.error(
                "'%s' not found in event %s [%s]",
                data_key_,
                str(list(event.keys())),
                str(e),
            )
            raise ValueError("expected %s key in event" % data_key_) from e
        except Exception as e:
            logger.error(
                "could not parse '%s' as json [%s]", data_key_, str(event[data_key_])
            )
            raise ValueError(
                "expected '%s' to be json formatted string" % data_key_
            ) from e
    elif isinstance(event[data_key_], (dict, list)):
        data = event[data_key_]
    else:
        logger.error(
            "unhandled submission type: '%s' [%s]",
            str(event[data_key_]),
            str(type(event[data_key_])),
        )

    if not data:
        logger.error("no data found in body")
        raise ValueError("no data in event: '%s'" % (str(event)))

    return data, mimetype or DEFAULT_MIMETYPE


def cors_headers():
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "Content-Type,Authorization,X-Api-Key",
        "Access-Control-Allow-Methods": "OPTIONS,GET,POST,PUT,DELETE,PATCH",
    }


def mk_error_resp(msg: str):
    return mk_resp(500, {"status": "error", "message": msg})


def mk_resp(statusCode, body, headers=None, **kwargs):
    """format a response for aws lambdas to aws apigw"""
    logger.debug("resp: %03i '%s', %s", statusCode, str(body), str(kwargs))

    if headers is None:
        headers = {}

    if isinstance(body, (dict, list)):
        try:
            body = json.dumps(body)
        except Exception as e:
            logger.exception("unable to serialise lambda response [%s]", str(e))
            return mk_error_resp(msg="unable to serialize response")

        headers.update({"Content-Type": "application/json"})

    if not isinstance(statusCode, int):
        raise ValueError("statusCode must be an integer")

    if not isinstance(body, str):
        raise ValueError("body must be a string [recv: '%s']" % str(type(body)))

    if APPEND_CORS_HEADERS:
        headers.update(cors_headers())

    return {"statusCode": statusCode, "body": body, "headers": headers, **kwargs}


_dynamodb = boto3.client("dynamodb", endpoint_url=os.getenv("DYNAMODB_ENDPOINT"))


def update_results_table(
    user_id: str,
    message_id: str,
    results_table: str,
    response: dict,
    status: str = "complete",
):
    """write polled results to the results table for caching"""
    try:
        _dynamodb.update_item(
            TableName=results_table,
            Key={"PK": {"S": user_id}, "SK": {"S": message_id}},
            UpdateExpression="SET #status = :status, #response = :response",
            ExpressionAttributeNames={"#status": "sts", "#response": "rsp"},
            ExpressionAttributeValues={
                ":status": {"S": status},
                ":response": {"S": json.dumps(response)},
            },
        )
        logger.info("[%s/%s] updated dynamodb", user_id, message_id)
    except ClientError as e:
        logger.error(
            "[%s/%s] failed to write on dynamodb:'%s' [%s]",
            user_id,
            message_id,
            results_table,
            str(e),
        )
        raise


def create_metric_object(user_id, model_type, model_name, metrics):
    return dict(
        user_id=user_id, operation=f"{model_type.value}/{model_name}", **metrics
    )


def update_metrics_sqs(
    user_id: str, model_type: ModelType, model_name: str, metrics: dict
):
    """write metrics to an sqs queue for logging"""
    sqs_client = boto3.client("sqs", endpoint_url=os.getenv("AWS_SQS_ENDPOINT_URL"))

    metrics_queue_url = os.getenv("METRICS_QUEUE_URL")

    if not metrics_queue_url:
        logger.warning("metrics_queue_url not found, no metric logging")
        return

    message_body = create_metric_object(user_id, model_type, model_name, metrics)

    logger.info("sending '%s' to '%s'", str(message_body), metrics_queue_url)

    try:
        response = sqs_client.send_message(
            QueueUrl=metrics_queue_url, MessageBody=json.dumps(message_body)
        )
        logger.info(
            "metrics sent to '%s' [%s]", metrics_queue_url, response["MessageId"]
        )
        return response["MessageId"]
    except Exception as e:
        logger.error("Failed to send metrics '%s' [%s]", metrics_queue_url, str(e))
        return None


def update_metrics_dynamodb(
    user_id: str, model_type: ModelType, model_name: str, metrics: dict
):
    """write metrics directly to dynamodb"""
    pk_pattern = "METRIC#RAW#USER#{user_id}"
    sk_pattern = "DATE#{date}#OP#{operation}"

    message_body = create_metric_object(user_id, model_type, model_name, metrics)

    operation = message_body.get("operation", "unknown")
    userid = message_body.get("user_id", "unknown")
    now = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

    item_data = dict(
        operation=operation,
        user_id=userid,
        date=now,
        data=json.dumps(message_body),
    )

    USAGE_TABLE_NAME = os.environ["DYNAMODB_USAGE_TABLE"]

    try:
        _dynamodb.put_item(
            TableName=USAGE_TABLE_NAME,
            Item={
                "PK": {"S": pk_pattern.format(**item_data)},
                "SK": {"S": sk_pattern.format(**item_data)},
                "operation": {"S": operation},
                "user_id": {"S": userid},
                "date": {"S": now},
                "data": {"S": json.dumps(message_body)},
            },
        )
    except Exception as e:
        logger.exception(
            "[%s/%s.%s] failed to write metrics to '%s' [%s]",
            user_id,
            model_type,
            model_name,
            USAGE_TABLE_NAME,
            str(e),
        )
        return


def update_metrics(user_id: str, model_type: ModelType, model_name: str, metrics: dict):
    """log metrics to a db via one of the implemented methods"""
    if "DYNAMODB_USAGE_TABLE" in os.environ:
        return update_metrics_dynamodb(user_id, model_type, model_name, metrics)
    elif "METRICS_QUEUE_URL" in os.environ:
        return update_metrics_sqs(user_id, model_type, model_name, metrics)
    else:
        logger.warning(
            "[%s/%s.%s] metrics not logged", user_id, model_type.value, model_name
        )


def record_usage(
    user_id: str,
    model_type: ModelType,
    modelname: str,
    duration: float,
    inference: float,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> ModelUsageStats:
    """simple wrapper to build a ModelUsageStats and call updated_metrics()"""
    usage = ModelUsageStats(
        duration=duration,
        inference=inference,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        memory_usage=get_memory_usage(),
    )
    update_metrics(user_id, model_type, modelname, usage.model_dump())
    return usage


def decode_image(b64_str: str) -> Image.Image:
    """Decode a base64 image string to a PIL Image.

    Accepts raw base64 or a data-URI prefix (data:image/jpeg;base64,...).
    """
    if b64_str.startswith("data:"):
        b64_str = b64_str.split(",", 1)[1]
    return Image.open(io.BytesIO(b64decode(b64_str))).convert("RGB")


def image_to_png_bytes(image: Image.Image) -> bytes:
    """convert an image to a png byte sequence"""
    with io.BytesIO() as buf:
        image.save(buf, format="PNG")
        return buf.getvalue()
