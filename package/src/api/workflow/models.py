"""
workflow_objects.py -- Marigold workflow DynamoDB object definitions.

All persistent workflow state is managed through these classes.
Key formats and access patterns are defined in CONTRACTS.md.

dynawrap DBItem handles PK/SK construction, serialisation, and
DynamoDB read/write. All classes are also pydantic BaseModels.

Utilities
---------
step_id(op)                     md5 hex digest of an op string
parse_workflow_execution_id     splits workflow_execution_id into components
"""

import hashlib
import json
from typing import Any, ClassVar

from dynawrap import DBItem
from pydantic import BaseModel

from runfox.backend.models import WorkflowRecord


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def step_id(op: str) -> str:
    """
    Produce a safe DynamoDB key component from a user-supplied op string.

    op values are user-provided and may contain the # delimiter or other
    characters unsafe in DynamoDB key expressions. The MD5 digest is
    deterministic, fixed-length, and delimiter-free.
    """
    return hashlib.md5(op.encode()).hexdigest()


def parse_workflow_execution_id(workflow_execution_id: str) -> tuple[str, str]:
    """
    Split a runfox workflow_execution_id into (workflow_id, execution_id).

    workflow_execution_id format: {workflow_id}#{execution_id}

    Raises ValueError if the format is not recognised.
    """
    parts = workflow_execution_id.split("#", 1)
    if len(parts) != 2:
        raise ValueError(
            f"Unrecognised workflow_execution_id format: {workflow_execution_id!r}"
        )
    return parts[0], parts[1]


# ---------------------------------------------------------------------------
# WorkflowTemplate
# ---------------------------------------------------------------------------


class WorkflowTemplate(DBItem, BaseModel):
    """
    A stored runfox YAML workflow template.

    Content-addressed: workflow_id is MD5 of the spec YAML, so submitting
    the same spec twice overwrites the same record. Ownership is per-user.

    Table:  WORKFLOW_TEMPLATE_TABLE
    PK:     USER#{user_id}
    SK:     TEMPLATE#{workflow_id}

    Access patterns:
        fetch one:      get-item on PK + SK
        list for user:  query PK=USER#{user_id}, SK begins_with "TEMPLATE#"
    """

    pk_pattern: ClassVar[str] = "USER#{user_id}"
    sk_pattern: ClassVar[str] = "TEMPLATE#{workflow_id}"

    user_id: str
    workflow_id: str
    name: str
    spec: str           # raw YAML string


# ---------------------------------------------------------------------------
# WorkflowExecution
# ---------------------------------------------------------------------------


class WorkflowExecution(DBItem, BaseModel):
    """
    Execution state for one run of a workflow template.

    One record per execution. Created at submission time. Updated in place
    after each advance() call by the executor Lambda. runfox_state is the
    sole store of WorkflowRecord state; it is opaque to all layers except
    DynamoDBStore and the executor Lambda.

    Table:  WORKFLOW_STATE_TABLE
    PK:     USER#{user_id}
    SK:     WORKFLOW#{workflow_id}#EXEC#{execution_id}

    Access patterns:
        fetch one:          get-item on PK + SK
        list for template:  query PK=USER#{user_id},
                            SK begins_with "WORKFLOW#{workflow_id}#EXEC#"
                            results are time-ordered (SK is lexicographically
                            sortable; execution_id begins with ISO timestamp)
        list all for user:  not supported; not required by the API
    """

    pk_pattern: ClassVar[str] = "USER#{user_id}"
    sk_pattern: ClassVar[str] = "WORKFLOW#{workflow_id}#EXEC#{execution_id}"

    user_id: str
    workflow_id: str
    execution_id: str
    status: str         # pending | in_progress | complete | halted | cancelled
    runfox_state: str   # JSON of WorkflowRecord.to_dict()
    created_at: str
    updated_at: str
    outcome: str | None = None  # JSON of resolved outputs; null until terminal

    # ------------------------------------------------------------------
    # runfox_state accessors
    # ------------------------------------------------------------------

    def get_workflow_record(self) -> WorkflowRecord:
        """Deserialise runfox_state into a WorkflowRecord."""
        return WorkflowRecord.from_dict(json.loads(self.runfox_state))

    def set_workflow_record(self, record: WorkflowRecord) -> "WorkflowExecution":
        """Return a new instance with runfox_state updated from a WorkflowRecord."""
        return self.model_copy(
            update={"runfox_state": json.dumps(record.to_dict())}
        )

    # ------------------------------------------------------------------
    # Composite key accessor
    # ------------------------------------------------------------------

    @property
    def workflow_execution_id(self) -> str:
        """Reconstruct the runfox workflow_execution_id from stored components."""
        return f"{self.workflow_id}#{self.execution_id}"


# ---------------------------------------------------------------------------
# WorkflowStep
# ---------------------------------------------------------------------------


class WorkflowStep(DBItem, BaseModel):
    """
    Observability record for one dispatch of one workflow step.

    One record per dispatch (i.e. per run_id). A step that retries
    produces one record per attempt. Created by SQSRunner.dispatch().
    Updated in place when the step result arrives.

    step_id is md5(op). The original op string is stored as an attribute
    for display purposes.

    Table:  WORKFLOW_STEPS_TABLE
    PK:     USER#{user_id}#WORKFLOW#{workflow_id}
    SK:     EXEC#{execution_id}#STEP#{step_id}#RUN#{run_id}

    Access patterns:
        all steps for an execution:
            query PK=USER#{user_id}#WORKFLOW#{workflow_id},
            SK begins_with "EXEC#{execution_id}#"

        all runs for a specific step:
            query PK=USER#{user_id}#WORKFLOW#{workflow_id},
            SK begins_with "EXEC#{execution_id}#STEP#{step_id}#"

        one specific run:
            get-item on full PK + SK

        undispatched steps (READY, dependencies unmet):
            no record exists; the step detail endpoint falls back to
            WorkflowRecord.steps in runfox_state on WorkflowExecution
    """

    pk_pattern: ClassVar[str] = "USER#{user_id}#WORKFLOW#{workflow_id}"
    sk_pattern: ClassVar[str] = "EXEC#{execution_id}#STEP#{step_id}#RUN#{run_id}"

    user_id: str
    workflow_id: str
    execution_id: str
    op: str             # original user-supplied step label
    step_id: str        # md5(op); use step_id() utility to construct
    run_id: int
    model_type: str
    model_name: str
    status: str         # dispatched | complete | failed
    submitted_at: str   # ISO 8601 UTC
    completed_at: str | None = None
    output: str | None = None   # JSON of step output dict; null until complete

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

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
        """
        Construct a WorkflowStep at dispatch time.

        Computes step_id from op. Sets status to dispatched.
        """
        return cls(
            user_id=user_id,
            workflow_id=workflow_id,
            execution_id=execution_id,
            op=op,
            step_id=step_id(op),
            run_id=run_id,
            model_type=model_type,
            model_name=model_name,
            status="dispatched",
            submitted_at=submitted_at,
        )

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    def complete(self, output: dict, completed_at: str) -> "WorkflowStep":
        """Return a new instance marked complete with output and timestamp."""
        return self.model_copy(update={
            "status": "complete",
            "output": json.dumps(output),
            "completed_at": completed_at,
        })

    def fail(self, completed_at: str) -> "WorkflowStep":
        """Return a new instance marked failed."""
        return self.model_copy(update={
            "status": "failed",
            "completed_at": completed_at,
        })
