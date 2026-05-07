"""Common cache management code.

All DynamoDB access goes through ResultsItem. No key strings are
constructed in this module. PK/SK patterns live in ResultsItem.
"""

import json
import logging
import os

import boto3
from dynawrap.backends.dynamodb import DynamoDBBackend

from shared.db_models import ResultsItem

logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL") or "INFO")

_ddb = boto3.client("dynamodb")
_dynawrap = DynamoDBBackend(_ddb)

DYNAMODB_TABLE = os.environ["DYNAMODB_TABLE"]

_DEFAULT_TTL_SECONDS = 86400 * 7  # one week


def make_api_job_id(message_id: str) -> str:
    """Job ID for a direct API job. Pass-through of message_id."""
    return message_id


def create_status(userid: str, message_id: str, ttl: int = None, status: str = "queued"):
    """Create a results item placeholder for a user message.

    ttl cannot be 0; a zero value is overridden by the default.
    """
    item = ResultsItem(
        user_id=userid,
        job_id=make_api_job_id(message_id),
        status=status,
        ttl=ttl or ResultsItem.make_ttl(),
    )
    _dynawrap.save(DYNAMODB_TABLE, item)


def update_status(userid: str, message_id: str, status: str):
    """Update the status field of an existing record without touching the TTL.

    Used to mark a job as 'error' after a failed SQS submission.
    """
    try:
        item = _dynawrap.get(DYNAMODB_TABLE, ResultsItem, user_id=userid, job_id=make_api_job_id(message_id))
        if item is None:
            logger.warning(
                "[%s/%s] update_status called but record not found", userid, message_id
            )
            return
        updated = item.model_copy(update={"status": status})
        _dynawrap.save(DYNAMODB_TABLE, updated)
        logger.info("[%s/%s] status updated to '%s'", userid, message_id, status)
    except Exception as e:
        logger.exception(
            "[%s/%s] failed to update status to '%s' [%s]",
            userid,
            message_id,
            status,
            str(e),
        )


def get_status(userid: str, message_id: str) -> str | None:
    item = _dynawrap.get(
        DYNAMODB_TABLE, ResultsItem,
        user_id=userid,
        job_id=make_api_job_id(message_id),
    )

    if item is None:
        logger.warning("[%s/%s] record not found", userid, message_id)
        return None

    return item.status


def get_response(userid: str, message_id: str) -> dict:
    item = _dynawrap.get(DYNAMODB_TABLE, ResultsItem, user_id=userid, job_id=make_api_job_id(message_id))
    if item is None:
        logger.warning("[%s/%s] record not found", userid, message_id)
        return {}
    if item.response is None:
        logger.warning("[%s/%s] response field is null", userid, message_id)
        return {}
    return json.loads(item.response)


def delete_cache(userid: str, message_id: str):
    # Construct the key directly from the class pattern; avoids a read
    # solely for the purpose of deletion. create_item_key is a class method
    # on DBItem and does not require a backend instance.
    item = _dynawrap.get(
        DYNAMODB_TABLE, ResultsItem,
        user_id=userid,
        job_id=make_api_job_id(message_id),
    )

    if item is None:
        logger.warning("[%s/%s] delete_cache: record not found", userid, message_id)
        return

    # FIXME: this is incorrect - we should build the key properly in dynawrap
    key = {
        "PK": {"S": f"USER#{userid}"},
        "SK": {"S": message_id},
    }

    _ddb.delete_item(TableName=DYNAMODB_TABLE, Key=key)
    logger.info("[%s/%s] deleted", userid, message_id)
