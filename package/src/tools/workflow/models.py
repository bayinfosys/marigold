"""
Workflow persistence models.

Item definitions for the workflow execution path -- dynawrap DBItem
subclasses (pydantic BaseModels underneath), so the same key-pattern
mechanism as shared/db_models.py applies here without any AWS-specific
assumption in the class definitions themselves.

Key formats and table schemas are defined in CONTRACTS.md.

Utilities
---------
step_id(op)                      md5 hex digest of a step op string
parse_workflow_execution_id(s)   splits workflow_execution_id into (workflow_id, execution_id)

NOTE: WorkflowStep previously lived in shared/db_models.py. It has been
moved here since this package (workflow) is its only consumer -- keeping
it in the shared module left a DynamoDB-only class with zero callers
once the AWS state machine was removed from master. See make_step_id
below and the module-level step_id() function -- these are currently
duplicate implementations of the same hash; worth collapsing to one.
"""

import hashlib
import json
from typing import ClassVar, Optional

from dynawrap import DBItem
from pydantic import BaseModel
from runfox.backend.models import WorkflowRecord

# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def step_id(op: str) -> str:
    """
    Produce a DynamoDB-style key component from a user-supplied op string.

    op values are user-provided and may contain the # delimiter or other
    characters that are unsafe in key expressions. The MD5 digest is
    deterministic, fixed-length, and delimiter-free.
    """
    return hashlib.md5(op.encode()).hexdigest()


def parse_workflow_execution_id(workflow_execution_id: str) -> tuple[str, str]:
    """
    Split a runfox workflow_execution_id into (workflow_id, execution_id).

    Format: {workflow_id}#{execution_id}

    Raises ValueError if the format is not recognised.
    """
    parts = workflow_execution_id.split("#", 1)
    if len(parts) != 2:
        raise ValueError(
            f"unrecognised workflow_execution_id format: {workflow_execution_id!r}"
        )
    return parts[0], parts[1]


# ---------------------------------------------------------------------------
# WorkflowStep  (moved from shared/db_models.py -- see module note above)
# ---------------------------------------------------------------------------


class WorkflowStep(DBItem, BaseModel):
    """
    Observability record for one dispatched workflow step.

    Written by SQSRunner.dispatch() with status='dispatched'.
    Updated by the worker with status='complete' on success.
    Read by the step detail API endpoints.

    A retry increments run_id and produces a new record (new SK).
    The step detail endpoint returns all runs ordered by run_id.

    PK and SK are derived from the workflow execution context carried
    in the message. step_id is md5(op) -- never constructed raw.
    """

    pk_pattern: ClassVar[str] = "USER#{user_id}#WORKFLOW#{workflow_id}"
    sk_pattern: ClassVar[str] = "EXEC#{execution_id}#STEP#{step_id}#RUN#{run_id}"

    user_id: str
    workflow_id: str
    execution_id: str
    op: str
    step_id: str
    run_id: int
    model_type: str
    model_name: str
    status: str
    submitted_at: str
    completed_at: Optional[str] = None
    output: Optional[str] = None

    @classmethod
    def from_dispatch(
        cls,
        user_id: str,
        workflow_id: str,
        execution_id: str,
        op: str,
        run_id: int,
        model_type: str,
        model_name: str,
        submitted_at: str,
    ) -> "WorkflowStep":
        return cls(
            user_id=user_id,
            workflow_id=workflow_id,
            execution_id=execution_id,
            op=op,
            step_id=cls.make_step_id(op),
            run_id=run_id,
            model_type=model_type,
            model_name=model_name,
            status="dispatched",
            submitted_at=submitted_at,
        )

    def complete(self, output: dict, completed_at: str) -> "WorkflowStep":
        return self.model_copy(
            update={
                "status": "complete",
                "output": json.dumps(output),
                "completed_at": completed_at,
            }
        )

    def fail(self, completed_at: str) -> "WorkflowStep":
        return self.model_copy(
            update={
                "status": "failed",
                "completed_at": completed_at,
            }
        )

    @staticmethod
    def make_step_id(op: str) -> str:
        return _md5(op.encode()).hexdigest()  # NOTE: duplicates step_id() above


from hashlib import md5 as _md5  # noqa: E402  -- see NOTE on make_step_id


# ---------------------------------------------------------------------------
# WorkflowTemplate
# ---------------------------------------------------------------------------


class WorkflowTemplate(DBItem, BaseModel):
    """
    A stored runfox YAML workflow template.

    Content-addressed: workflow_id is MD5 of the spec YAML, so submitting
    the same spec twice overwrites the same record.

    Table:  WORKFLOW_TEMPLATE_TABLE
    PK:     USER#{user_id}
    SK:     TEMPLATE#{workflow_id}
    """

    pk_pattern: ClassVar[str] = "USER#{user_id}"
    sk_pattern: ClassVar[str] = "TEMPLATE#{workflow_id}"

    user_id: str
    workflow_id: str
    name: str
    spec: str  # raw YAML string
    created_at: str


# ---------------------------------------------------------------------------
# WorkflowExecution
# ---------------------------------------------------------------------------


class WorkflowExecution(DBItem, BaseModel):
    """
    Execution state for one run of a workflow template.

    One record per execution. Created at submission time. Updated in place
    after each advance() call by the executor. runfox_state is the sole
    store of WorkflowRecord state and is opaque to all layers except the
    runfox Store implementation and the executor.

    Table:  WORKFLOW_STATE_TABLE
    PK:     USER#{user_id}
    SK:     WORKFLOW#{workflow_id}#EXEC#{execution_id}
    """

    pk_pattern: ClassVar[str] = "USER#{user_id}"
    sk_pattern: ClassVar[str] = "WORKFLOW#{workflow_id}#EXEC#{execution_id}"

    user_id: str
    workflow_id: str
    execution_id: str
    status: str  # pending | in_progress | complete | halted | cancelled
    runfox_state: str  # JSON of WorkflowRecord.to_dict()
    created_at: str
    updated_at: str
    outcome: Optional[str] = None  # JSON of resolved outputs; null until terminal

    @property
    def workflow_execution_id(self) -> str:
        return f"{self.workflow_id}#{self.execution_id}"

    def get_workflow_record(self) -> WorkflowRecord:
        return WorkflowRecord.from_dict(json.loads(self.runfox_state))

    def set_workflow_record(self, record: WorkflowRecord) -> "WorkflowExecution":
        return self.model_copy(update={"runfox_state": json.dumps(record.to_dict())})
