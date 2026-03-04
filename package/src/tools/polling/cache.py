"""common cache managment code"""

import json
import logging
import os
import time

import boto3

logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL") or "INFO")

dynamodb = boto3.client("dynamodb")

DYNAMODB_TABLE = os.environ["DYNAMODB_TABLE"]


def create_key(userid, message_id):
    return {
        "PK": {"S": userid},
        "SK": {"S": message_id},
    }


def create_status(userid: str, message_id: str, ttl: int = -1, status: str = "queued"):
    # Default TTL: one week from submission time
    if ttl < 0:
        ttl = int(time.time()) + (86400 * 7)

    dynamodb.put_item(
        TableName=DYNAMODB_TABLE,
        Item={
            "PK": {"S": userid},
            "SK": {"S": message_id},
            "sts": {"S": status},
            "ttl": {"N": str(ttl)},
        },
    )


def update_status(userid: str, message_id: str, status: str):
    """Update the status field of an existing record without touching the TTL.

    Used to mark a job as 'error' after a failed SQS submission, ensuring the
    record does not remain as a stale 'queued' entry that blocks client retries.
    """
    try:
        dynamodb.update_item(
            TableName=DYNAMODB_TABLE,
            Key={"PK": {"S": userid}, "SK": {"S": message_id}},
            UpdateExpression="SET #sts = :status",
            ExpressionAttributeNames={"#sts": "sts"},
            ExpressionAttributeValues={":status": {"S": status}},
        )
        logger.info("[%s/%s] status updated to '%s'", userid, message_id, status)
    except Exception as e:
        logger.exception(
            "[%s/%s] failed to update status to '%s' [%s]",
            userid,
            message_id,
            status,
            str(e),
        )


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

    return {}  # Item not found


def delete_cache(userid, message_id):
    """delete an item from the cache
    TODO: add a conditional delete where we can delete all caches related to a particular model
    """
    key = create_key(userid, message_id)

    response = dynamodb.delete_item(TableName=DYNAMODB_TABLE, Key=key)

    logger.info("[%s/%s] delete: '%s'", userid, message_id, str(response))

    return
