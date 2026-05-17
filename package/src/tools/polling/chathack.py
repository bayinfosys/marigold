import os
import json
import boto3
from hashlib import md5

from shared.lambda_proxy import mk_resp
from shared.sqs_models import MarigoldSQSMessage

from .cache import create_status, get_status

ANONCHAT_QUEUE_URL = os.environ.get("ANONCHAT_QUEUE_URL", "")
ANONCHAT_MODEL = os.environ.get("ANONCHAT_MODEL", "qwen/qwen3-8b")


sqs = boto3.client("sqs")


def handle_chat_submission(userid, event):
    body = event["body"]
    body_md5 = md5(body.encode()).hexdigest()
    message_id = "API#" + body_md5

    existing = get_status(userid, message_id)
    if existing:
        return mk_resp(200, {"message_id": body_md5, "status": existing})

    try:
        content = json.loads(body)
    except json.JSONDecodeError:
        return mk_resp(400, {"status": "error", "message": "invalid json"})

    if not content.get("messages"):
        return mk_resp(400, {"status": "error", "message": "messages required"})

    create_status(userid, message_id, status="queued")

    msg = MarigoldSQSMessage(
        user_id=userid,
        message_id=message_id,
        model_type="instruct",
        model_name=ANONCHAT_MODEL,
        model_inputs=content,
    )

    sqs.send_message(
        QueueUrl=ANONCHAT_QUEUE_URL,
        MessageBody=msg.model_dump_json(),
    )

    return mk_resp(200, {"message_id": body_md5})
