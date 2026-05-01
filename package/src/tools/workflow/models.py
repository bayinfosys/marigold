"""
Workflow persistence models.

DynamoDB item definitions for the workflow execution path.
All classes are dynawrap DBItem subclasses and pydantic BaseModels.

Key formats and table schemas are defined in CONTRACTS.md.

Utilities
---------
step_id(op)                      md5 hex digest of a step op string
parse_workflow_execution_id(s)   splits workflow_execution_id into (workflow_id, execution_id)
"""

import hashlib
import json
from typing import ClassVar, Optional

from dynawrap import DBItem
from pydantic import BaseModel
from runfox.backend.models import WorkflowRecord

from shared.db_models import WorkflowStep

# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def step_id(op: str) -> str:
    """
    Produce a DynamoDB key component from a user-supplied op string.

    op values are user-provided and may contain the # delimiter or other
    characters that are unsafe in DynamoDB key expressions. The MD5 digest
    is deterministic, fixed-length, and delimiter-free.
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
    after each advance() call by the executor Lambda. runfox_state is the
    sole store of WorkflowRecord state and is opaque to all layers except
    DynamoDBStore and the executor Lambda.

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
