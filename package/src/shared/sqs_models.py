"""
shared/sqs_models.py -- Marigold SQS message contract.

Defines the canonical message shape for all Marigold SQS queues.
Used by:
  - tools/workflow/runner.py      (dispatch, message construction)
  - tools/workflow/model_dummy.py (worker, message parsing)
  - package/src/models/*.py       (ECS workers, message parsing)
  - tools/polling/ecs.py          (direct API path, message construction)

Top-level fields are Marigold routing and observability metadata.
model_inputs is the payload passed verbatim to the model handler.
"""

from typing import Any, Dict, Optional
from pydantic import BaseModel

from hashlib import md5 as _md5


class MarigoldSQSMessage(BaseModel):
    """
    Canonical SQS message body for all Marigold model queues.

    Top-level fields are consumed by Marigold infrastructure:
    routing, logging, result storage, workflow state advancement.

    model_inputs is opaque to Marigold -- it is passed verbatim to
    the model handler. Keys and value types are model-specific.
    """

    user_id: str
    message_id: str
    model_type: str
    model_name: str
    model_inputs: Dict[str, Any]

    # Workflow fields -- null for direct API requests
    workflow_execution_id: Optional[str] = None
    op: Optional[str] = None
    run_id: Optional[int] = None


def make_job_id(message: "MarigoldSQSMessage") -> str:
    """Derive a stable unique job_id for a results cache record.

    For direct API jobs (no workflow_execution_id):
        the message_id is already unique -- returned as-is.

    For workflow step jobs:
        md5 of workflow_execution_id#op#run_id. The inclusion of run_id
        means retries produce distinct job_ids. Fixed-length regardless
        of component length.
    """
    if message.workflow_execution_id is None:
        return message.message_id
    key = f"{message.workflow_execution_id}#{message.op}#{message.run_id}"
    return _md5(key.encode()).hexdigest()
