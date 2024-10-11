import json
import boto3
import os
import logging
import time

from hashlib import md5

logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL") or "INFO")

sfn = boto3.client("stepfunctions")
dynamodb = boto3.client("dynamodb")

SUBMISSION_PATH = os.environ["INPUT_PATH"]
STATUS_PATH = os.environ["POLL_PATH"]
SFN_ARN = os.environ["SFN_ARN"]
DYNAMODB_TABLE = os.environ["DYNAMODB_TABLE"]


def get_userid_from_event(event):
    try:
        return event["requestContext"]["identity"]["apiKey"]
    except KeyError:
        logger.error("requestContext.identity.apiKey not found in '%s'", str(event))
        return "dummy"  # FIXME: return 400


def get_path_from_event(event):
    """NB: this can be event.resource, event.requestContext.resourcePath,
    but not event.path
    """
    return event["resource"]


def cors_headers():
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "Content-Type,Authorization,X-Api-Key",
        "Access-Control-Allow-Methods": "OPTIONS,GET,POST,PUT,DELETE,PATCH",
    }


def mk_resp(statusCode, body, **kwargs):
    return {
        "statusCode": statusCode,
        "body": body,
        "headers": {**cors_headers(), **kwargs.get("headers", {})},
        **{k: v for k, v in kwargs.items() if k not in ("headers",)},
    }


def handler(event, context):
    logger.info("event: '%s'", str(event))

    path = get_path_from_event(event)
    userid = get_userid_from_event(event)

    handlers = {SUBMISSION_PATH: handle_submission, STATUS_PATH: handle_status}

    try:
        return handlers[path](userid, event)
    except KeyError as e:
        logger.error("unhandled path: '%s' [%s]", str(e), str(list(handlers.keys())))
        return mk_resp(400, json.dumps("Invalid path"))
    except Exception as e:
        logger.exception("unknown exception in handler: '%s'", str(e))
        return mk_resp(500, "internal error")


def handle_submission(userid, event):
    # message_id = str(uuid.uuid4())
    message_id = md5(event["body"].encode("utf-8")).hexdigest()
    message_content = json.loads(event["body"])

    # Set the TTL to be 24 hours (86400 seconds) from now
    ttl_timestamp = int(time.time()) + 86400

    # Write initial record to DynamoDB
    dynamodb.put_item(
        TableName=DYNAMODB_TABLE,
        Item={
            "PK": {"S": userid},
            "SK": {"S": message_id},
            "Status": {"S": "started"},
            "ttl": {"N": str(ttl_timestamp)},
        },
    )

    # Start the Step Functions state machine
    # TODO: check response values
    sfn.start_execution(
        stateMachineArn=SFN_ARN,
        input=json.dumps(
            {
                "destination": {"userid": userid, "message_id": message_id},
                "input": message_content,
            }
        ),
    )

    return mk_resp(200, json.dumps({"message_id": message_id}))


def handle_status(userid, event):
    """read the status field from dynamodb
    if status == "complete", we load item.response.s as a json object and return it
    the response written to dynamodb MUST be a valid lambda response object
    """
    try:
        message_id = event["pathParameters"]["message_id"]
    except KeyError as e:
        logger.error("cannot extract message_id from event [%s]", str(e))
        return mk_resp(400, "message_id required")

    # Query DynamoDB for the message status
    response = dynamodb.get_item(
        TableName=DYNAMODB_TABLE,
        Key={"PK": {"S": userid}, "SK": {"S": message_id}},
    )

    if "Item" in response:
        status = response["Item"]["Status"]["S"]
        logger.info("found item: '%s'", str(response["Item"]))
        if status == "complete":
            return mk_resp(200, response["Item"]["Response"]["S"])
        else:
            return mk_resp(202, json.dumps({"status": status}))
    else:
        logger.warning("'%s/%s' item not found", userid, message_id)
        return mk_resp(404, "%s not found" % message_id)
