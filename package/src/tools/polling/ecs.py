"""polling implementation against the ecs cluster

there exist task definitions for each model
this lambda:
+ checks the cache
+ on-miss: invoke run task of the model on ecs
+ on-hit: return the value

TODO: note the running models in an dynamodb lookup table [later]

refs:
https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task-cpu-memory-error.html
"""

import json
import logging
import os
from hashlib import md5

import boto3
from api.models import ModelDispatch, ModelDispatchRoutes
from shared.lambda_proxy import get_path_from_event, get_userid_from_event, mk_resp

from .cache import create_status, delete_cache, get_response, get_status, update_status

logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL") or "INFO")

s3 = boto3.client("s3")
sqs = boto3.client("sqs")
dynamodb = boto3.client("dynamodb")

# env vars
DYNAMODB_TABLE = os.environ["DYNAMODB_TABLE"]


_config: ModelDispatchRoutes = {}


def load_model_config() -> ModelDispatchRoutes:
    global _config

    if _config:
        return _config

    bucket = os.environ["AWS_S3_ASSETS_BUCKET_NAME"]
    key = os.environ["MODELS_CONFIG_S3_OBJECT"]
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
        data = json.loads(obj["Body"].read())
        _config = {model_name: ModelDispatch(**v) for model_name, v in data.items()}
        logger.info("loaded %d models", len(_config))
    except Exception as e:
        logger.exception("failed to load model config from s3: %s", str(e))
        raise

    return _config


## get it at launch
load_model_config()

assert _config, "unable to load MODELS_CONFIG"


class TaskLauncher:
    def __init__(self, ecs_client, cluster_arn, subnets, security_groups):
        self.ecs = ecs_client
        self.cluster = cluster_arn
        self.subnets = subnets
        self.security_groups = security_groups

    def is_running(self, model: ModelDispatch) -> bool:
        """check if a task for this model is already running
        TODO: move this to a dynamodb 'running_models' table rather than an ecs lookup
        TODO: check sqs queue depth with `ApproximateNumberOfMessages` and start extra task if needed
        """
        # NB: we do not sortkeys in the hash here because the hash originally happened in
        # step functions and we could not sort. So, we allow cache-miss on key order change.
        resp = self.ecs.list_tasks(
            cluster=self.cluster,
            desiredStatus="RUNNING",
            family=model.family,
            maxResults=5,
        )
        return bool(resp.get("taskArns"))

    def launch(self, model: ModelDispatch):
        """launch the ecs task for this model"""
        logger.info("launching ecs task for '%s'", model.family)

        self.ecs.run_task(
            cluster=self.cluster,
            launchType="FARGATE",
            taskDefinition=model.task_definition,
            count=1,
            networkConfiguration={
                "awsvpcConfiguration": {
                    "subnets": self.subnets,
                    "securityGroups": self.security_groups,
                }
            },
        )


launcher = TaskLauncher(
    ecs_client=boto3.client("ecs"),
    cluster_arn=os.environ["ECS_CLUSTER_ARN"],
    subnets=os.environ["ECS_SUBNETS"].split(","),
    security_groups=os.environ["ECS_SECURITY_GROUPS"].split(","),
)


def handler(event, context):
    logger.info("event: '%s'", str(event))

    path = get_path_from_event(event)
    method = event["httpMethod"]
    userid = get_userid_from_event(event)

    dispatch = {
        "POST": handle_submission,
        "GET": handle_status,
        "DELETE": delete_status,
        "OPTIONS": lambda u, e: mk_resp(200, {}),
    }

    fn = dispatch.get(method)
    if fn is None:
        return mk_resp(405, {"status": "error", "message": "method not allowed"})

    try:
        return fn(userid, event)
    except Exception as e:
        logger.exception("error in handler: %s", str(e))
        return mk_resp(500, {"status": "error", "message": "internal error"})


def handle_submission(userid, event):
    message_id = md5(event["body"].encode("utf-8")).hexdigest()
    message_content = json.loads(event["body"])

    model_name = message_content.get("model")
    if not model_name:
        return mk_resp(400, {"status": "error", "message": "model field required"})

    # check cache first
    existing_status = get_status(userid, message_id)
    # TODO: have multiple status, some are `overwritable` (stale, internal error, etc)
    if existing_status:
        logger.info("[%s/%s] cache item found", userid, message_id)
        return mk_resp(200, {"message_id": message_id, "status": existing_status})

    # load the model store metadata
    models = load_model_config()
    model_name_md5 = md5(model_name.encode()).hexdigest()

    # find the model we are supposed to use for this message
    try:
        dispatch = models[model_name_md5]
    except KeyError:
        logger.warning("[%s] unknown model requested: '%s'", userid, model_name)
        return mk_resp(400, {"status": "error", "message": "unknown model"})

    # TODO: validate the request against the model type, so we can return 400 error without starting a task...

    create_status(userid, message_id, status="queued")
    logger.info("[%s/%s] queued for model '%s'", userid, message_id, model_name)

    # submit the request to the model via sqs
    try:
        sqs.send_message(
            QueueUrl=dispatch.queue_url,
            MessageBody=json.dumps(
                {
                    "userid": userid,
                    "message_id": message_id,
                    "request": message_content,
                }
            ),
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

    # launch an ecs task for processing if necessary
    if not launcher.is_running(dispatch):
        logger.info("[%s/%s] launching task for %s", userid, message_id, model_name)
        launcher.launch(dispatch)

    # return the message_id for cache polling
    return mk_resp(200, {"message_id": message_id})


def handle_status(userid, event):
    """fetch the status of this message from dyanmodb
    NB: this is a good candidate for direct apigw integration
    """
    message_id = event["pathParameters"]["message_id"]
    status = get_status(userid, message_id)

    if status in ("complete", "error"):
        result = get_response(userid, message_id)
        return mk_resp(
            200, {"status": status, "message_id": message_id, "result": result}
        )
    elif status:
        return mk_resp(202, {"status": status, "message_id": message_id})
    else:
        return mk_resp(404, {"status": "not found", "message_id": message_id})


def delete_status(userid, event):
    """remove the status of work from dynamodb
    this is a cache clearance method
    NB: good candidate for direct apigw integration
    """
    message_id = event["pathParameters"]["message_id"]
    delete_cache(userid, message_id)
    return mk_resp(
        200, {"status": "ok", "message": "deleted", "message_id": message_id}
    )
