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
