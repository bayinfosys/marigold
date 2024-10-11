"""shared functions usable by all models
+ lambda base64 decoder
"""
import os
import base64
import logging
import json


logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL") or "INFO")


DEFAULT_MIMETYPE = "text/plain"
APPEND_CORS_HEADERS = os.getenv("APPEND_CORS_HEADERS") or False


def lambda_event_to_data(event, data_key: str = None):
    """extract image/text data from the apigw integration

    NB: this is somewhat hacked, we don't have a way to reliably
        get the mimetype of the binary content from the event, so
        we rely on the user to encode correctly

    NB: when each model type has an associated pydantic model for input
        we should pass that model as a parameter and do validation on
        the key value.
    """
    #     data_key = "Body"
    data_key_ = data_key or "input"
    mimetype = None

    if event.get("isBase64Encoded"):
        b64_str = event["body"]

        if not b64_str:
            raise ValueError("empty body [%s, %s]" % (str(event), str(type(b64_str))))

        # check if the base64 string includes a mimetype
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
            logger.error("'%s' not found in event %s [%s]", data_key_, str(list(event.keys())), str(e))
            raise ValueError("expected %s key in event" % data_key_) from e
        except Exception as e:
            logger.error("could not parse '%s' as json [%s]", data_key_, str(event[data_key_]))
            raise ValueError("expected '%s' to be json formatted string" % data_key_) from e
    elif isinstance(event[data_key_], (dict, list)):
        data = event[data_key_]
    else:
        logger.error("unhandled submission type: '%s' [%s]", str(event[data_key_]), str(type(event[data_key_])))

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
    """format a response for aws lambdas to aws apigw

    set the APPEND_CORS_HEADERS environment variable to
    insert cors headers into response
    """
    logger.debug("resp: %03i '%s', %s", statusCode, str(body), str(kwargs))

    if isinstance(body, (dict, list)):
        try:
            body = json.dumps(body)
        except Exception as e:
            logger.exception("unable to serialise lambda response [%s]", str(e))
            return mk_error_resp(msg="unable to serialize response")

    if not isinstance(statusCode, int):
        raise ValueError("statusCode must be an integer")

    if not isinstance(body, str):
        raise ValueError("body must be a string")

    if headers is None:
        headers = {}

    if APPEND_CORS_HEADERS:
        headers.update(cors_headers())

    return {
        "statusCode": statusCode,
        "body": body,
        "headers": headers,
        **kwargs
    }


def update_results_table(user_id: str, message_id: str, results_table: str, results: dict, status: str = "complete"):
    """write polled results to the results table for caching
    NB: we pass in 'results_table' but it could be an environment variable
    """
    dynamodb = boto3.resource("dynamodb", endpoint_url=os.getenv("DYNAMODB_ENDPOINT"))

    try:
        table = dynamodb.Table(results_table)
    except Exception as e:
        logger.exception("[%s/%s] unable to find dynamodb:'%s'", user_id, message_id, results_table)
        raise e

    try:
        table.update_item(
            Key={"PK": user_id, "SK": message_id},
            UpdateExpression="SET #status = :status, #response = :response",
            ExpressionAttributeNames={"#status": "Status", "#response": "Response"},
            ExpressionAttributeValues={
                ":status": status,
                ":response": json.dumps(response),
            },
        )
        logger.info("[%s/%s] updated dynamodb", user_id, message_id)
    except ClientError as e:
        logger.error("[%s/%s] failed to write on dynamodb:'%s' [%s]", user_id, message_id, results_table, str(e))
        raise
