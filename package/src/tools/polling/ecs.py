"""Polling Lambda: submission and status for direct API requests.

Submission path:
  - Checks the results cache for a prior result on the same request body.
  - On miss: writes queued status, sends MarigoldSQSMessage to the model
    queue, launches an ECS task if none is running for that model.
  - On hit: returns the cached status without starting a new task.

The message_id is the MD5 of the request body. This provides request
deduplication: identical requests from any source return the cached result
without spawning a new task. The API Gateway request_id is logged alongside
the MD5 so that duplicate requests can be traced in CloudWatch.

The message_id is prefixed API# per the job ID convention in CONTRACTS.md.
"""

import json
import logging
import os
from hashlib import md5

import boto3

from shared.models import ModelDispatch, ModelDispatchRoutes
from shared.lambda_proxy import get_path_from_event, get_userid_from_event, mk_resp
from shared.sqs_models import MarigoldSQSMessage

from .cache import create_status, delete_cache, get_response, get_status, update_status
from .chathack import handle_chat_submission

logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL") or "INFO")

s3 = boto3.client("s3")
sqs = boto3.client("sqs")
dynamodb = boto3.client("dynamodb")


# ---------------------------------------------------------------------------
# Model config
# ---------------------------------------------------------------------------


_config: ModelDispatchRoutes = {}
_cache_state: dict = {}


def load_model_config() -> ModelDispatchRoutes:
    global _config

    if _config:
        return _config

    bucket = os.environ["AWS_S3_ASSETS_BUCKET_NAME"]
    key = os.environ["MODELS_CONFIG_S3_OBJECT"]
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
        data = json.loads(obj["Body"].read())
        _config = {name: ModelDispatch(**v) for name, v in data.items()}
        logger.info("loaded %d models", len(_config))
    except Exception as e:
        logger.exception("failed to load model config from s3: %s", str(e))
        raise

    return _config


def load_cache_state() -> dict:
    global _cache_state

    if _cache_state:
        return _cache_state

    bucket = os.environ["AWS_S3_ASSETS_BUCKET_NAME"]
    key = os.environ.get("CACHE_STATE_S3_OBJECT", "cache_state.json")

    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
        data = json.loads(obj["Body"].read())
        _cache_state = data.get("models", {})
        logger.info("loaded cache state for %d models", len(_cache_state))
    except Exception as e:
        logger.warning("failed to load cache state: %s -- skipping cache check", str(e))
        return {}

    return _cache_state


load_model_config()
load_cache_state()
assert _config, "unable to load MODELS_CONFIG"
assert _cache_state, "unable to load CACHE_STATE"

# ---------------------------------------------------------------------------
# Launch type
# ---------------------------------------------------------------------------

def get_launch_kwargs(dispatch: ModelDispatch, user_tier: str = "free") -> dict:
    provider = {
        "lrg": os.environ.get("ECS_CAPACITY_PROVIDER_GPU_LRG"),
        "sm":  os.environ.get("ECS_CAPACITY_PROVIDER_GPU_SM"),
    }.get(dispatch.gpu_tier, os.environ.get("ECS_CAPACITY_PROVIDER_BIG_CPU"))

    return {
        "capacityProviderStrategy": [{
            "capacityProvider": provider,
            "weight": 1,
            "base":   0,
        }]
    }


# ---------------------------------------------------------------------------
# Task launcher
# ---------------------------------------------------------------------------


class TaskLauncher:
    def __init__(self, ecs_client, cluster_arn, subnets, security_groups):
        self.ecs = ecs_client
        self.cluster = cluster_arn
        self.subnets = subnets
        self.security_groups = security_groups

    def is_running(self, model: ModelDispatch) -> bool:
        """Check if a task for this model family is already running.

        TODO: replace ECS list_tasks with a DynamoDB running_models table.
        TODO: check ApproximateNumberOfMessages on the SQS queue and launch
              additional tasks when depth exceeds a threshold.
        """
        resp = self.ecs.list_tasks(
            cluster=self.cluster,
            desiredStatus="RUNNING",
            family=model.family,
            maxResults=5,
        )
        return bool(resp.get("taskArns"))

    def is_pending(self, model: ModelDispatch) -> bool:
        """Check if a task for this model family is pending (container starting,
        model not yet loaded). A pending task must block new launches just as
        a running task does -- model load times of 400-700s create a large
        window where is_running returns False but a task is already in flight."""
        resp = self.ecs.list_tasks(
            cluster=self.cluster,
            desiredStatus="PENDING",
            family=model.family,
            maxResults=5,
        )
        return bool(resp.get("taskArns"))

    def is_active(self, model: ModelDispatch) -> bool:
        """Return True if any task for this model is running or pending."""
        return self.is_running(model) or self.is_pending(model)

    def launch(self, model: ModelDispatch, user_tier: str = "free", token: str = ""):
        logger.info("launching ecs task for '%s'", model.family)
        launch_kwargs = get_launch_kwargs(model, user_tier)
        self.ecs.run_task(
            cluster=self.cluster,
            taskDefinition=model.task_definition,
            #clientToken=model.family,  # idempotency token
            count=1,
            networkConfiguration={
                "awsvpcConfiguration": {
                    "subnets": self.subnets,
                    "securityGroups": self.security_groups,
                }
            },
            **launch_kwargs,
        )


launcher = TaskLauncher(
    ecs_client=boto3.client("ecs"),
    cluster_arn=os.environ["ECS_CLUSTER_ARN"],
    subnets=os.environ["ECS_SUBNETS"].split(","),
    security_groups=os.environ["ECS_SECURITY_GROUPS"].split(","),
)


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


def handler(event, context):
    logger.info("polling lambda version=%s", os.getenv("BUILD_VERSION", "unknown"))
    logger.debug("event: '%s'", str(event))

    method = event["httpMethod"]
    userid = get_userid_from_event(event)

    dispatch = {
        "POST": handle_submission,
        "GET": handle_status,
        "DELETE": delete_status,
        "OPTIONS": lambda u, e: mk_resp(200, {}),
    }

    try:
        return dispatch[method](userid, event)
    except KeyError as e:
        logger.warning("'%s' not found for '%s'", str(e), str(event))
        return mk_resp(405, {"status": "error", "message": "method not allowed"})
    except Exception as e:
        logger.exception("error in handler: %s", str(e))
        return mk_resp(500, {"status": "error", "message": "internal error"})


def handle_submission(userid, event):
    body = event["body"]
    request_id = event.get("requestContext", {}).get("requestId", "unknown")
    body_md5 = md5(body.encode("utf-8")).hexdigest()
    message_id = "API#" + body_md5

    path = event.get("path", "")

    # HACK - demo chat
    # /demo/chat shortcut -- routes directly to the anonchat queue
    # no model lookup, no ECS launch, always-on service handles it
    if path.startswith("/demo/chat"):
        return handle_chat_submission(userid, event)
    # HACK - end

    logger.info("[%s/%s] request_id=%s", userid, message_id, request_id)

    message_content = json.loads(body)

    model_name = message_content.get("model")
    if not model_name:
        return mk_resp(400, {"status": "error", "message": "model field required"})

    model_name = model_name.lower()  # force it to lowercase

    # check if this message is already on the queue
    existing_status = get_status(userid, message_id)
    if existing_status:
        logger.info(
            "[%s/%s] cache hit status='%s' request_id=%s",
            userid,
            message_id,
            existing_status,
            request_id,
        )
        return mk_resp(200, {"message_id": body_md5, "status": existing_status})

    # compute the model name hash
    model_name_md5 = md5(model_name.encode()).hexdigest()

    # get the list of available models, queues, etc
    models = load_model_config()

    # attempt to get the dispatch function
    try:
        dispatch = models[model_name_md5]
    except KeyError:
        logger.warning("[%s] unknown model requested: '%s'", userid, model_name)
        return mk_resp(400, {"status": "error", "message": "unknown model"})

    # verify the model is in the actual cache, not just requested
    cache_state = load_cache_state()
    if not cache_state:
        logger.critical("[%s] cache state unavailable -- rejecting request", userid)
        return mk_resp(503, {"status":  "error", "message": "service_unavailable", "detail":  "cache state could not be loaded"})

    model_cache = cache_state.get(model_name)
    if not model_cache:
        logger.critical("[%s] model not in cache state: '%s'", userid, model_name)
        return mk_resp(400, {"status":  "error", "message": "model_not_available", "model":   model_name})

    if model_cache.get("status") != "ok":
        logger.critical("[%s] model cache status is not ok: '%s' status=%s", userid, model_name, model_cache.get("status"))
        return mk_resp(400, {"status":  "error", "message": "model_not_available", "model":   model_name, "cache_status": model_cache.get("status")})


    # all seems fine, go ahead and create a status row to update on progress
    create_status(userid, message_id, status="queued")
    logger.info("[%s/%s] queued for model '%s'", userid, message_id, model_name)

    msg = MarigoldSQSMessage(
        user_id=userid,
        message_id=message_id,
        model_type=dispatch.model_type,
        model_name=model_name,
        model_inputs=message_content,
    )

    try:
        sqs.send_message(
            QueueUrl=dispatch.queue_url,
            MessageBody=msg.model_dump_json(),
        )
    except sqs.exceptions.QueueDoesNotExist as e:
        logger.critical(
            "[%s/%s] queue does not exist: %s [%s]",
            userid,
            message_id,
            dispatch.queue_url,
            str(e),
        )
        update_status(userid, message_id, status="error")
        return mk_resp(500, {"status": "error", "message": "internal routing error"})
    except Exception as e:
        logger.exception("[%s/%s] unknown error sending to SQS: '%s'", userid, message_id, str(e))
        update_status(userid, message_id, status="error")
        return mk_resp(500, {"status": "error", "message": "internal error"})

    if not launcher.is_active(dispatch):
        logger.info("[%s/%s] launching task for '%s'", userid, message_id, model_name)
        update_status(userid, message_id, "provisioning")
        try:
            launcher.launch(dispatch, token=body_md5)
        except Exception as e:
            # NB: this is not an error, the task is not initiated but the job is in the queue
            # TODO: have a watch dog to check for queues which are not being served and start a worker
            logger.critical("[%s/%s] failed to launch task for '%s'", userid, message_id, model_name)

    return mk_resp(200, {"message_id": body_md5})


def handle_status(userid, event):
    raw_id = event["pathParameters"]["message_id"]
    message_id = f"API#{raw_id}"
    status = get_status(userid, message_id)

    if status in ("complete", "error"):
        result = get_response(userid, message_id)
        return mk_resp(
            200, {"status": status, "message_id": raw_id, "result": result}
        )
#    # TODO: when we have the dynamodb tracking of jobs, we should respond with instance providing info to the user
#    elif status == "provisioning":
#        model_state = get_model_state(model_hash)
#        if model_state:
#            hint = {
#                "loading":  "Model loading on GPU instance, ~%ds remaining" % estimated_remaining(model_state),
#                "ready":    "Worker ready, processing your request shortly",
#            }.get(model_state["status"], "GPU instance starting")
#        else:
#            hint = "GPU instance starting, estimated wait 3-5 minutes"
#
#        return mk_resp(202, {
#            "status":    "provisioning",
#            "message_id": raw_id,
#            "hint":      hint,
#        })
    elif status:
        return mk_resp(202, {"status": status, "message_id": raw_id})
    else:
        return mk_resp(404, {"status": "not found", "message_id": raw_id})


def delete_status(userid, event):
    raw_id = event["pathParameters"]["message_id"]
    message_id = f"API#{raw_id}"
    delete_cache(userid, message_id)
    return mk_resp(200, {"status": "ok", "message": "deleted", "message_id": raw_id})
