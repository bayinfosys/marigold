"""fetch usage stats from the local api db

test with:

```json
{
  "requestContext": {"authorizer": {"email": "anax@hotmail.co.uk"}},
  "resource": "/usage/month/1"
}
```
"""
import os
import logging

import json
import boto3

from boto3.dynamodb.conditions import Key
from botocore.exceptions import BotoCoreError, ClientError

from shared import get_userid_from_event, get_path_from_event, mk_resp


logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL") or "INFO")

dynamodb = boto3.resource("dynamodb")

PK = "METRIC#SUM#USER#{user_id}"
SK = "DATE_RANGE#{date_range_type}#{date_range_key}#OP#{operation}"
USAGE_TABLE_NAME = os.environ["DYNAMODB_USAGE_TABLE"]


def handler(event, context):
    logger.info("event: '%s'", str(event))

    path = get_path_from_event(event)
    user_id = get_userid_from_event(event)

    logger.debug("[%s/%s] fetch", user_id, path)

    # set the parameters from the path
    if event["pathParameters"]["key"] == "month":
        date_range_type = "M"
    elif event["pathParameters"]["key"] == "day":
        date_range_type = "D"
    else:
        logger.error(
            "[%s/%s] invalid pathParameters: '%s'",
            user_id,
            path,
            str(event["pathParameters"]),
        )
        return mk_resp(400, {"status": "error", "message": "not found"})

    period = event["pathParameters"].get("period")

    if not period:
        if date_range_type == "M":
            period = datetime.now().strftime("%Y%m")
        else:
            period = datetime.now().strftime("%Y%m%d")

    # FIXME: check a query string to get the "last" parameter
    last = 10  # last 10 days/months
    operation = "ALL"

    # fetch from dynamodb
    items = get_data(user_id, operation, date_range_type, period, last)

    logger.info("[%s/%s] found %i items", user_id, operation, len(items))

    if items:
        return mk_resp(200, [json.loads(item["data"]) for item in items])
    else:
        return mk_resp(200, [])


def get_data(user_id, operation, date_range_type, period, count):
    """Retrieve the metric data from DynamoDB
    Get the `top` latest items sorted by the `date` attribute
    TODO: allow a fixed date_range_key to get from a particular date
    """
    # make a query and sort by the date attribute
    table = dynamodb.Table(USAGE_TABLE_NAME)

    key = {
        "PK": PK.format(user_id=user_id),
        "SK": SK.format(
            date_range_type=date_range_type,
            date_range_key=period,
            operation=operation,
        ),
    }

    key_expr = Key("PK").eq(key["PK"]) & Key("SK").begins_with(key["SK"])

    logger.info("[%s/%s] query: '%s'", user_id, operation, str(key))
    logger.info("[%s/%s] querying: '%s'", user_id, operation, str(key_expr))

    try:
        response = table.query(
            TableName=USAGE_TABLE_NAME,
            KeyConditionExpression=key_expr,
            ScanIndexForward=False,  # Set to False for desc (latest first)
            Limit=count,  # FIXME: take a limit from somewhere, paginate?
        )
    except (BotoCoreError, ClientError) as e:
        logger.error("[%s/%s] error [%s]", user_id, operation, str(e))
        return None

    logger.info("[%s/%s] resp: '%s'", user_id, operation, str(response))

    return response.get("Items")
