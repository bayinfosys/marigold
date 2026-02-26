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
import boto3
import os
import logging
from hashlib import md5

from shared import get_userid_from_event, get_path_from_event, mk_resp
from api.models import (
    InternalModelDescription,
    ModelType,
    InstructModelRequest,
    EmbedTextRequest,
    # TTSRequest,
)
from .cache import create_status, get_status, get_response, delete_cache

logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL") or "INFO")

s3 = boto3.client("s3")
sqs = boto3.client("sqs")
dynamodb = boto3.client("dynamodb")

# env vars
DYNAMODB_TABLE = os.environ["DYNAMODB_TABLE"]

# API paths
SUBMISSION_PATH = os.environ["SUBMISSION_PATH"]
STATUS_PATH = os.environ["STATUS_PATH"]
DELETE_PATH = os.environ["DELETE_PATH"]

_config: dict[str, InternalModelDescription] = {}


def load_model_config() -> dict[str, InternalModelDescription]:
    global _config
    if _config is not None:
        return _config

    bucket = os.environ["AWS_S3_ASSETS_BUCKET_NAME"]
    key = os.environ["MODELS_CONFIG_S3_OBJECT"]
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
        data = json.loads(obj["Body"].read())
        _config = {
            model_name: InternalModelDescription(**v) for model_name, v in data.items()
        }
        logger.info("loaded %d models", len(_config))
    except Exception as e:
        logger.exception("failed to load model config from s3: %s", str(e))
        raise

    return _config


## get it at launch
load_model_config()

assert _config is not None, "unable to load MODELS_CONFIG"


class TaskLauncher:
    def __init__(self, ecs_client, cluster_arn, subnets, security_groups):
        self.ecs = ecs_client
        self.cluster = cluster_arn
        self.subnets = subnets
        self.security_groups = security_groups

    def is_running(self, model: InternalModelDescription) -> bool:
        """check if a task for this model is already running
        TODO: move this to a dynamodb 'running_models' table rather than an ecs lookup
        TODO: check sqs queue depth with `ApproximateNumberOfMessages` and start extra task if needed
        """
        # NB: we do not sortkeys in the hash here because the hash originally happened in
        # step functions and we could not sort. So, we allow cache-miss on key order change.
        family = md5(model.name.encode()).hexdigest()
        resp = self.ecs.list_tasks(
            cluster=self.cluster,
            desiredStatus="RUNNING",
            family=family,
            maxResults=5,
        )
        return bool(resp.get("taskArns"))

    def launch(self, model: InternalModelDescription):
        """launch the ecs task for this model"""
        logger.info("launching ecs task for '%s'", model.name)

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
            overrides={
                "containerOverrides": [
                    {
                        "name": "infer",
                        "environment": [
                            {"name": "AWS_SQS_QUEUE_URL", "value": model.queue_url},
                        ],
                    }
                ]
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
    userid = get_userid_from_event(event)

    handlers = {
        SUBMISSION_PATH: handle_submission,
        STATUS_PATH: handle_status,
        DELETE_PATH: delete_status,
    }

    try:
        return handlers[path](userid, event)
    except KeyError:
        logger.error("invalid path: '%s'", path)
        return mk_resp(400, {"status": "error", "message": "invalid path"})
    except Exception as e:
        logger.exception("error in handler: %s", str(e))
        return mk_resp(500, {"status": "error", "message": "internal error"})


def handle_submission(userid, event):
    message_id = md5(event["body"].encode("utf-8")).hexdigest()
    message_content = json.loads(event["body"])

    # check cache first
    existing_status = get_status(userid, message_id)
    # TODO: have multiple status, some are `overwritable` (stale, internal error, etc)
    if existing_status:
        logger.info("[%s/%s] cache item found", userid, message_id)
        return mk_resp(200, {"message_id": message_id, "status": existing_status})

    # load the model store metadata
    models = load_model_config()
    model_name = message_content["model"]
    model_name_md5 = md5(message_content["model"].encode()).hexdigest()

    # NB: we must parse `message_content` into an appropriate request
    # (InstructRequest, EmbeddingRequest, TTSRequest, etc)
    # TODO: ensure api.models has a common Request base model which we can use
    #       and differentiate based on model.model_type
    try:
        model = models[model_name_md5]
    except KeyError as e:
        logger.error(
            "cannot find '%s' in %s [%s]",
            model_name,
            str([k for k in _config]),
            str(type(e)),
        )
        return mk_resp(400, {"status": "error", "message": "unknown model"})

    # parse the object according to the model
    try:
        match model.type:
            case ModelType.INSTRUCT:
                request = InstructModelRequest.model_validate(message_content)
            case ModelType.TEXT_EMBEDDING:
                request = EmbedTextRequest.model_validate(message_content)
            case _:
                return mk_resp(
                    400,
                    {
                        "status": "error",
                        "message": "unknown model type '%s'" % model.type.value,
                    },
                )
    except Exception as e:
        logger.error(
            "unable to parse submission '%s' for '%s' [%s]",
            str(message_content),
            model_name,
            str(e),
        )
        return mk_resp(
            400, {"status": "error", "message": "unable to parse submission"}
        )

    # the submission is valid, so create a new item in the cache
    create_status(userid, message_id)
    logger.info("[%s/%s] new cache item created", userid, message_id)

    # submit the request to the model via sqs
    try:
        sqs.send_message(
            QueueUrl=model.queue_url,
            MessageBody=json.dumps(
                {
                    "userid": userid,
                    "message_id": message_id,
                    "request": request.model_dump(),
                }
            ),
        )
    except sqs.exceptions.QueueDoesNotExist as e:
        logger.critical(
            "[%s/%s] queue does not exist: %s [%s]",
            userid,
            message_id,
            model.queue_url,
            str(e),
        )
        return mk_resp(500, {"status": "error", "message": "internal routing error"})
    except Exception as e:
        logger.exception("[%s/%s] unknown error: '%s'", userid, message_id, str(e))
        return mk_resp(500, {"status": "error", "message": "internal error"})

    # launch an ecs task for processing if necessary
    if not launcher.is_running(model):
        logger.info("[%s/%s] launching task for %s", userid, message_id, model_name)
        launcher.launch(model)

    # return the message_id for cache polling
    return mk_resp(200, {"message_id": message_id})


def handle_status(userid, event):
    """fetch the status of this message from dyanmodb
    NB: this is a good candidate for direct apigw integration
    """
    message_id = event["pathParameters"]["message_id"]
    status = get_status(userid, message_id)

    if status in ("complete", "error"):
        response = get_response(userid, message_id)
        response["status"] = status
        return mk_resp(200, response)
    elif status:
        return mk_resp(202, {"status": status})
    else:
        return mk_resp(404, {"status": "not found"})


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
