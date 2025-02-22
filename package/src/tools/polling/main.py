import json
import boto3
import os
import logging
import time

from hashlib import md5

from shared import get_userid_from_event, get_path_from_event, mk_resp

logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL") or "INFO")

sfn = boto3.client("stepfunctions")
dynamodb = boto3.client("dynamodb")

SUBMISSION_PATH = os.environ["SUBMISSION_PATH"]
STATUS_PATH = os.environ["STATUS_PATH"]
DELETE_PATH = os.environ["DELETE_PATH"]
SFN_ARN = os.environ["SFN_ARN"]
DYNAMODB_TABLE = os.environ["DYNAMODB_TABLE"]


def handler(event, context):
    logger.info("event: '%s'", str(event))

    path = get_path_from_event(event)
    userid = get_userid_from_event(event)

    handlers = {
        SUBMISSION_PATH: handle_submission,
        STATUS_PATH: handle_status,
        DELETE_PATH: delete_status,
    }

    try:
        return handlers[path](userid, event)
    except KeyError as e:
        logger.error("unhandled path: '%s' [%s]", str(e), str(list(handlers.keys())))
        return mk_resp(400, {"status": "error", "message": "invalid path"})
    except Exception as e:
        logger.exception("unknown exception in handler: '%s'", str(e))
        return mk_resp(500, {"status": "error", "message": "internal error"})


def create_key(userid, message_id):
    return {
        "PK": {"S": userid},
        "SK": {"S": message_id},
    }


def get_status(userid, message_id):
    """Retrieve the status of an item from DynamoDB using attribute projection."""
    key = create_key(userid, message_id)

    response = dynamodb.get_item(
        TableName=DYNAMODB_TABLE,
        Key=key,
        ProjectionExpression="sts",  # only get status attribute
    )

    if "Item" in response and "sts" in response["Item"]:
        # FIXME: raise a notfound exception?
        return response["Item"]["sts"]["S"]
    else:
        logger.warning("[%s/%s] no response for '%s'", userid, message_id, str(key))

    return None  # Item not found


def get_response(userid, message_id) -> dict:
    """Retrieve the response attribute of an item from DynamoDB using attribute projection."""
    key = create_key(userid, message_id)

    response = dynamodb.get_item(
        TableName=DYNAMODB_TABLE,
        Key=key,
        ProjectionExpression="rsp",  # only response attribute
    )

    if "Item" in response and "rsp" in response["Item"]:
        logger.debug(
            "[%s/%s] response: '%s' [%s]",
            userid,
            message_id,
            str(response["Item"]["rsp"]["S"]),
            str(type(response["Item"]["rsp"]["S"])),
        )
        return json.loads(response["Item"]["rsp"]["S"])
    else:
        logger.warning("[%s/%s] no response for '%s'", userid, message_id, str(key))

    return None  # Item not found


def delete_cache(userid, message_id):
    """delete an item from the cache
    TODO: add a conditional delete where we can delete all caches related to a particular model
    """
    key = create_key(userid, message_id)

    response = dynamodb.delete_item(TableName=DYNAMODB_TABLE, Key=key)

    logger.info("[%s/%s] delete: '%s'", userid, message_id, str(response))

    return


def handle_submission(userid, event):
    # message_id = str(uuid.uuid4())
    message_id = md5(event["body"].encode("utf-8")).hexdigest()
    message_content = json.loads(event["body"])

    # Check if the item already exists in DynamoDB
    existing_status = get_status(userid, message_id)

    if existing_status:
        logger.info(
            "[%s/%s] existing item found '%s'", userid, message_id, existing_status
        )
        return mk_resp(200, {"message_id": message_id, "status": existing_status})

    # Set the TTL to be 24 hours (86400 seconds) from now
    ttl_timestamp = int(time.time()) + 86400

    # Write initial record to DynamoDB
    dynamodb.put_item(
        TableName=DYNAMODB_TABLE,
        Item={
            "PK": {"S": userid},
            "SK": {"S": message_id},
            "sts": {"S": "started"},
            "ttl": {"N": str(ttl_timestamp)},
        },
    )

    # Start the Step Functions state machine
    # TODO: check response values
    response = sfn.start_execution(
        stateMachineArn=SFN_ARN,
        input=json.dumps(
            {
                "destination": {"userid": userid, "message_id": message_id},
                "body": message_content,  # sometimes this is 'input' sometimes 'body'
            }
        ),
    )

    logger.info("[%s/%s] started execution '%s'", userid, message_id, str(response))

    return mk_resp(200, {"message_id": message_id})


def handle_status(userid, event):
    """read the status field from dynamodb
    if status == "complete", we load item.response.s as a json object and return it
    the response written to dynamodb MUST be a valid lambda response object
    """
    try:
        message_id = event["pathParameters"]["message_id"]
    except KeyError as e:
        logger.error("Cannot extract message_id from event [%s]", str(e))
        return mk_resp(400, {"status": "error", "message": "message_id required"})

    # Get the status of the item
    status = get_status(userid, message_id)

    if status:
        if status in (
            "complete",
            "error",
        ):  # these are end states, and we should return the response
            response_content = get_response(userid, message_id)  # Get the response
            response_content.update({"status": status})
            logger.info("[%s/%s] status: '%s'", userid, message_id, status)
            return mk_resp(200, response_content)
        else:
            logger.info("[%s/%s] status: '%s'", userid, message_id, str(status))
            return mk_resp(202, {"status": status})
    else:
        logger.warning("[%s/%s] item not found", userid, message_id)
        return mk_resp(404, {"status": "not found"})


def delete_status(userid, event):
    """delete the response from dynamodb (clear the cache of a particular value)

    NB: if the existing status is not 'complete' we should error until it is complete
        or have way to cancel the job (I prefer not to cancel jobs tbh)

    FIXME: check the cache result exists and return 404 if not
    """
    try:
        message_id = event["pathParameters"]["message_id"]
    except KeyError as e:
        logger.error("Cannot extract message_id from event [%s]", str(e))
        return mk_resp(400, {"status": "error", "message": "message_id required"})

    delete_cache(userid, message_id)

    return mk_resp(200, {"status": "ok", "message": "deleted", "message_id": message_id})
