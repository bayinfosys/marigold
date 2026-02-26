"""API key management lambda

Handles create, list, and delete of API Gateway API keys for programmatic
access to the Marigold API. All routes are protected by the Cognito authorizer,
so the caller's email is available from JWT claims.

The key naming convention is:
    {email}/{label}

This allows listing all keys for a user via the nameQuery prefix filter,
and resolving owner and label from the name without additional storage.

NB: the raw key value is only returned at creation time. It cannot be
    retrieved afterwards. The caller must store it immediately.
"""
import json
import logging
import os

import boto3
from shared import mk_resp

logger = logging.getLogger()
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))

client = boto3.client("apigateway")

USAGE_PLAN_NAME = os.environ["USAGE_PLAN_NAME"]

def get_usage_plan_id() -> str:
    plans = client.get_usage_plans()
    for plan in plans["items"]:
        if plan["name"] == USAGE_PLAN_NAME:
            return plan["id"]
    raise RuntimeError("usage plan '%s' not found" % USAGE_PLAN_NAME)

USAGE_PLAN_ID = get_usage_plan_id()


def get_email_from_event(event) -> str:
    """extract email from cognito jwt claims"""
    try:
        return event["requestContext"]["authorizer"]["claims"]["email"]
    except KeyError:
        raise ValueError("email claim not found in authorizer context")


def handle_create(email: str, event: dict) -> dict:
    try:
        body = json.loads(event.get("body") or "{}")
    except Exception:
        return mk_resp(400, {"status": "error", "message": "invalid request body"})

    label = body.get("label", "default")

    key = client.create_api_key(
        name=f"{email}/{label}",
        enabled=True,
    )
    client.create_usage_plan_key(
        usagePlanId=USAGE_PLAN_ID,
        keyId=key["id"],
        keyType="API_KEY",
    )
    return mk_resp(201, {"id": key["id"], "name": key["name"], "value": key["value"]})


def handle_list(email: str, event: dict) -> dict:
    paginator = client.get_paginator("get_api_keys")
    keys = []
    for page in paginator.paginate(nameQuery=f"{email}/", includeValues=False):
        keys.extend([
            {"id": k["id"], "name": k["name"]}
            for k in page["items"]
        ])
    return mk_resp(200, keys)


def handle_delete(email: str, event: dict) -> dict:
    key_id = (event.get("pathParameters") or {}).get("key_id")
    if not key_id:
        return mk_resp(400, {"status": "error", "message": "key_id required"})

    try:
        key = client.get_api_key(apiKey=key_id, includeValue=False)
    except client.exceptions.NotFoundException:
        return mk_resp(404, {"status": "error", "message": "key not found"})

    if not key["name"].startswith(f"{email}/"):
        return mk_resp(403, {"status": "error", "message": "forbidden"})

    client.delete_api_key(apiKey=key_id)
    return mk_resp(200, {"status": "ok"})


HANDLERS = {
    ("POST",   "/keys"):          handle_create,
    ("GET",    "/keys"):          handle_list,
    ("DELETE", "/keys/{key_id}"): handle_delete,
}


def lambda_handler(event, context):
    logger.info("event: '%s'", str(event))

    try:
        email = get_email_from_event(event)
    except ValueError as e:
        return mk_resp(401, {"status": "error", "message": str(e)})

    route = (event.get("httpMethod"), event.get("resource"))
    handler = HANDLERS.get(route)

    if not handler:
        return mk_resp(400, {"status": "error", "message": "unhandled route '%s %s'" % route})

    try:
        return handler(email, event)
    except Exception as e:
        logger.exception("unhandled error in %s %s [%s]", *route, str(e))
        return mk_resp(500, {"status": "error", "message": "internal error"})
