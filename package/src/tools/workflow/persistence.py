"""
workflow/persistence.py -- writes for workflow step outcomes.

Moved from backend/persistence.py. Its only real dependency was
WorkflowStep, which lives in this package now (workflow/models.py) --
this always belonged here, independent of the AWS question.

FIXME (aws-removal): _dynawrap was built directly from a boto3 DynamoDB
client. That construction is gone; this needs an injected dynawrap
DBBackend instead (see the same TODO in model_dummy.py -- both want
the same fix, and probably the same injected object).
"""

import json
import logging
import os
from datetime import datetime, timezone

from shared.schedule_models import MarigoldMessage

from .models import WorkflowStep

logger = logging.getLogger(__name__)


# TODO: replace with an injected dynawrap DBBackend (Postgres or
# whatever main.py wires up), passed into these functions rather than
# constructed at module import time -- mirrors receiver_logic.py /
# results_cache.py, which already take an injected backend. Both
# functions below currently need a steps_table string AND a backend;
# once injected, consider whether they should become methods on a
# small WorkflowStepWriter class instead of two free functions each
# re-reading WORKFLOW_STEPS_TABLE from the environment.
_dynawrap = None


def write_workflow_step_complete(sqs_msg: MarigoldMessage, output: dict):
    steps_table = os.getenv("WORKFLOW_STEPS_TABLE")
    if not steps_table:
        logger.warning(
            "[%s/%s] WORKFLOW_STEPS_TABLE not set, skipping step write",
            sqs_msg.user_id,
            sqs_msg.message_id,
        )
        return

    workflow_id, execution_id = sqs_msg.workflow_execution_id.split("#", 1)
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    step = WorkflowStep(
        user_id=sqs_msg.user_id,
        workflow_id=workflow_id,
        execution_id=execution_id,
        op=sqs_msg.op,
        step_id=WorkflowStep.make_step_id(sqs_msg.op),
        run_id=sqs_msg.run_id,
        model_type=sqs_msg.model_type,
        model_name=sqs_msg.model_name,
        status="complete",
        submitted_at=now,
        completed_at=now,
        output=json.dumps(output),
    )

    try:
        # FIXME: _dynawrap is None until the backend is injected (see
        # module docstring) -- this raises AttributeError if called.
        _dynawrap.save(steps_table, step)
        logger.info(
            "[%s/%s] workflow step complete written",
            sqs_msg.user_id,
            sqs_msg.message_id,
        )
    except Exception as e:
        logger.exception(
            "[%s/%s] failed to write workflow step complete [%s]",
            sqs_msg.user_id,
            sqs_msg.message_id,
            str(e),
        )


def write_workflow_step_failed(sqs_msg: MarigoldMessage, error: str):
    steps_table = os.getenv("WORKFLOW_STEPS_TABLE")
    if not steps_table:
        logger.warning(
            "[%s/%s] WORKFLOW_STEPS_TABLE not set, skipping step failure write",
            sqs_msg.user_id,
            sqs_msg.message_id,
        )
        return

    workflow_id, execution_id = sqs_msg.workflow_execution_id.split("#", 1)
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    step = WorkflowStep(
        user_id=sqs_msg.user_id,
        workflow_id=workflow_id,
        execution_id=execution_id,
        op=sqs_msg.op,
        step_id=WorkflowStep.make_step_id(sqs_msg.op),
        run_id=sqs_msg.run_id,
        model_type=sqs_msg.model_type,
        model_name=sqs_msg.model_name,
        status="failed",
        submitted_at=now,
        completed_at=now,
        output=json.dumps({"error": error}),
    )

    try:
        # FIXME: same as above -- _dynawrap is a stub.
        _dynawrap.save(steps_table, step)
    except Exception as e:
        logger.exception(
            "[%s/%s] failed to write workflow step failure [%s]",
            sqs_msg.user_id,
            sqs_msg.message_id,
            str(e),
        )
