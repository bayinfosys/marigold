"""
ASG lifecycle hook handler.

Transforms EC2 AutoScaling lifecycle hook events into LifecycleEvent
SNS messages compatible with the Marigold state machine.

Handles:
    autoscaling:EC2_INSTANCE_LAUNCHING    -> INSTANCE_START
    autoscaling:EC2_INSTANCE_TERMINATING  -> INSTANCE_TERMINATE
"""

import json
import logging
import os

import boto3
from shared.sns_models import EventType, LifecycleEvent

log = logging.getLogger(__name__)
log.setLevel(os.getenv("LOG_LEVEL", "INFO"))

ec2 = boto3.client("ec2")
sns = boto3.client("sns")
autoscaling = boto3.client("autoscaling")

LIFECYCLE_TOPIC_ARN = os.environ["LIFECYCLE_TOPIC_ARN"]

TRANSITION_EVENT_MAP = {
    "autoscaling:EC2_INSTANCE_LAUNCHING": EventType.INSTANCE_START,
    "autoscaling:EC2_INSTANCE_TERMINATING": EventType.INSTANCE_TERMINATE,
}


def get_instance_info(instance_id: str) -> dict:
    resp = ec2.describe_instances(InstanceIds=[instance_id])
    inst = resp["Reservations"][0]["Instances"][0]
    return {
        "instance_id": instance_id,
        "instance_type": inst["InstanceType"],
        "spot": inst.get("InstanceLifecycle") == "spot",
    }


def complete_hook(
    hook_name: str, asg_name: str, instance_id: str, result: str = "CONTINUE"
) -> None:
    autoscaling.complete_lifecycle_action(
        LifecycleHookName=hook_name,
        AutoScalingGroupName=asg_name,
        InstanceId=instance_id,
        LifecycleActionResult=result,
    )


def handler(event, context):
    for record in event.get("Records", []):
        try:
            body = json.loads(record["Sns"]["Message"])
        except Exception as e:
            log.error("failed to parse record: %s", e)
            continue

        transition = body.get("LifecycleTransition", "")
        instance_id = body.get("EC2InstanceId", "")
        hook_name = body.get("LifecycleHookName", "")
        asg_name = body.get("AutoScalingGroupName", "")

        event_type = TRANSITION_EVENT_MAP.get(transition)
        if not event_type:
            log.debug("unhandled transition %s -- skipping", transition)
            continue

        try:
            info = get_instance_info(instance_id)
        except Exception as e:
            log.error("describe_instances failed for %s: %s", instance_id, e)
            complete_hook(hook_name, asg_name, instance_id, result="ABANDON")
            continue

        evt = LifecycleEvent(
            event_type=event_type,
            model_name="",
            model_hash="",
            message_id=None,
            payload=info,
        )

        try:
            sns.publish(**evt.to_sns_kwargs(LIFECYCLE_TOPIC_ARN))
            log.info(
                "%s  instance=%s  type=%s  spot=%s",
                event_type,
                instance_id,
                info["instance_type"],
                info["spot"],
            )
        except Exception as e:
            log.error("sns publish failed: %s", e)
            complete_hook(hook_name, asg_name, instance_id, result="ABANDON")
            continue

        complete_hook(hook_name, asg_name, instance_id)
