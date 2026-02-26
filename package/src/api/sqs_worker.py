import os
import logging
import json
import boto3
from time import perf_counter as clock

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

from shared import (
    get_userid_from_event,
    lambda_event_to_data,
    mk_resp,
    update_results_table,
    get_memory_usage,
    update_metrics,
)


class SQSWorker:
    def __init__(self, queue_url: str, model):
        self.queue_url = queue_url
        self.model = model
        self.client = boto3.client("sqs")

    def handle_message(self, msg):
        """should return:
        + user_id: str
        + message_id: str
        + model response object: derived from basemodel
        """
        raise NotImplementedError()

    def run(self):
        while True:
            # FIXME: implement signal handling and shutdown hooks
            response = self.client.receive_message(
                QueueUrl=self.queue_url,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=20,
                VisibilityTimeout=30,
            )
            messages = response.get("Messages", [])

            if not messages:
                logger.debug("sqs response with no messages [%s]", str(response))
                break
            else:
                logger.info("recv %i messages", len(messages))

            for msg in messages:
                logger.info("msg: %s", json.dumps(msg))
                receipt_handle = msg["ReceiptHandle"]

                # FIXME: extend visibility every 20 seconds during processing
                try:
                    user_id, message_id, result = self.handle_message(msg)
                    update_results_table(user_id, message_id, os.environ["RESULTS_TABLE"], result.model_dump())
                    self.client.delete_message(QueueUrl=self.queue_url, ReceiptHandle=receipt_handle)
                except Exception as e:
                    logger.error("unable to process message [%s]", str(e))
