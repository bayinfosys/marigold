"""AWS Lambda proxy integration utilities.

Handles the Lambda proxy contract: parsing API Gateway events, extracting
identity, and formatting responses. Only needed by Lambda handler functions;
ECS SQS workers do not use this module.
"""
import boto3
import base64
import json
import logging
import os

logger = logging.getLogger(__name__)

DEFAULT_MIMETYPE = "text/plain"

APPEND_CORS_HEADERS = os.getenv("APPEND_CORS_HEADERS", "False").lower() in (
    "true",
    "1",
    "t",
)


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

_apigw = boto3.client("apigateway")
_key_cache: dict[str, str] = {}


def _resolve_api_key(api_key_id: str) -> str:
    """
    Resolve an API Gateway key ID to a user identity via GetApiKey.

    Uses the key name as the user identity -- set this to the user's
    email or account identifier when creating the key via POST /users/keys.

    Result is cached at container level; key-to-identity mapping is stable.
    """
    if api_key_id in _key_cache:
        return _key_cache[api_key_id]

    response = _apigw.get_api_key(apiKey=api_key_id)

    if not response.get("enabled"):
        raise RuntimeError(f"API key {api_key_id!r} is disabled")

    name = response.get("name")
    if not name:
        raise RuntimeError(f"API key {api_key_id!r} has no name")

    # name format is {email}/{label} -- extract email as the user identity
    user_id = name.split("/")[0]
    _key_cache[api_key_id] = user_id
    return user_id


def get_userid_from_event(event: dict) -> str:
    if "requestContext" in event:
        authorizer = event["requestContext"].get("authorizer", {})
        if authorizer.get("email"):
            return authorizer["email"]

        identity = event["requestContext"].get("identity", {})
        api_key_id = identity.get("apiKeyId")
        if api_key_id:
            return _resolve_api_key(api_key_id)

        raise RuntimeError(
            "requestContext present but no identity path found. "
            "event=%s" % str(event)
        )

    if "destination" in event:
        try:
            return event["destination"]["userid"]
        except KeyError:
            raise RuntimeError(
                "destination.userid not found in event. event=%s" % str(event)
            )

    raise RuntimeError(
        "Neither requestContext nor destination present in event. "
        "event=%s" % str(event)
    )


def get_path_from_event(event: dict) -> str:
    """Return the HTTP method and resource path as a single string.

    Matches the path format used in the OpenAPI spec, e.g. "POST /embed/text".
    """
    event_path = "%s %s" % (event["httpMethod"], event["resource"])
    assert event_path.split(" ")[0] in ("OPTIONS", "GET", "POST", "DELETE")
    return event_path


def path_handler(path: str, registry: dict):
    """Decorator to register a function as a handler for a given path."""

    def decorator(func):
        registry[path] = func
        return func

    return decorator


# ---------------------------------------------------------------------------
# Request body parsing
# ---------------------------------------------------------------------------


def lambda_event_to_data(event: dict, data_key: str = None):
    """Extract request data from an API Gateway Lambda proxy event.

    Handles base64-encoded binary bodies, JSON strings, and pre-parsed
    dicts/lists. Returns (data, mimetype).
    """
    data_key_ = data_key or "input"
    mimetype = None

    if event.get("isBase64Encoded"):
        b64_str = event["body"]

        if not b64_str:
            raise ValueError("empty body in event")

        if b64_str.startswith("data:"):
            header, b64_str = b64_str[5:].split(",", 1)
            mimetype = header.split(";")[0]

        try:
            data = base64.b64decode(b64_str)
        except Exception as e:
            logger.exception("unable to decode base64 body [%s]", str(e))
            raise

    elif isinstance(event.get(data_key_), str):
        try:
            data = json.loads(event[data_key_])
        except KeyError as e:
            raise ValueError("expected '%s' key in event" % data_key_) from e
        except Exception as e:
            raise ValueError("expected '%s' to be a JSON string" % data_key_) from e

    elif isinstance(event.get(data_key_), (dict, list)):
        data = event[data_key_]

    else:
        raise ValueError(
            "unhandled body type '%s' for key '%s'"
            % (type(event.get(data_key_)).__name__, data_key_)
        )

    if not data:
        raise ValueError("no data found in event body")

    return data, mimetype or DEFAULT_MIMETYPE


# ---------------------------------------------------------------------------
# Response formatting
# ---------------------------------------------------------------------------


def cors_headers() -> dict:
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "Content-Type,Authorization,X-Api-Key",
        "Access-Control-Allow-Methods": "OPTIONS,GET,POST,PUT,DELETE,PATCH",
    }


def mk_resp(status_code: int, body, headers: dict = None, **kwargs) -> dict:
    """Format a response dict for the Lambda proxy integration."""
    logger.debug("resp: %03i '%s'", status_code, str(body))

    if not isinstance(status_code, int):
        raise ValueError("status_code must be an integer")

    if headers is None:
        headers = {}

    if isinstance(body, (dict, list)):
        try:
            body = json.dumps(body)
        except Exception as e:
            logger.exception("unable to serialise response body [%s]", str(e))
            body = json.dumps({"status": "error", "message": "unable to serialize response"})
            status_code = 500

        headers["Content-Type"] = "application/json"

    if not isinstance(body, str):
        raise ValueError("body must be a string, got '%s'" % type(body).__name__)

    if APPEND_CORS_HEADERS:
        headers.update(cors_headers())

    return {"statusCode": status_code, "body": body, "headers": headers, **kwargs}


def mk_error_resp(msg: str) -> dict:
    return mk_resp(500, {"status": "error", "message": msg})
