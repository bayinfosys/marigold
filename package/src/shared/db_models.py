"""
shared/db_models.py -- DynamoDB item definitions for shared tables.

PK/SK patterns are the authoritative source for all key construction.
Values are sourced from CONTRACTS.md. No key strings are constructed
anywhere outside this module.

All items use boto3.client("dynamodb") wire format via to_dynamo_item().
Never use boto3.resource or Table objects with these items.
"""

import json
from typing import Optional
from pydantic import BaseModel
from dynawrap import DBItem

import time
from typing import ClassVar

from hashlib import md5 as _md5

_DEFAULT_TTL_OFFSET = 86400 * 30  # 30 days


class ResultsItem(DBItem, BaseModel):
    """One inference result record in the results cache.

    job_id is an opaque unique identifier for the inference job.
    The caller is responsible for constructing job_id before creating
    this record. ResultsItem has no knowledge of how job_id is derived.
    """

    pk_pattern: ClassVar[str] = "USER#{user_id}"
    sk_pattern: ClassVar[str] = "{job_id}"

    default_ttl_offset: ClassVar[int] = _DEFAULT_TTL_OFFSET

    user_id:  str
    job_id:   str
    status:   str
    response: Optional[str] = None
    ttl:      Optional[int] = None

    @classmethod
    def make_ttl(cls, offset_seconds: int = None) -> int:
        offset = (
            offset_seconds if offset_seconds is not None else cls.default_ttl_offset
        )
        return int(time.time()) + offset


class WorkflowStep(DBItem, BaseModel):
    """
    Observability record for one dispatched workflow step.

    Written by SQSRunner.dispatch() with status='dispatched'.
    Updated by the ECS worker with status='complete' on success.
    Read by the step detail API endpoints.

    A retry increments run_id and produces a new record (new SK).
    The step detail endpoint returns all runs ordered by run_id.

    PK and SK are derived from the workflow execution context carried
    in the SQS message. step_id is md5(op) -- never constructed raw.

    This is defined by the runfox library integration
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
        return _md5(op.encode()).hexdigest()
