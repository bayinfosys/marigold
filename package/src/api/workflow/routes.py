"""
workflows.py -- Workflow API route definitions.

Imported and registered in routes.py. Follows the same pattern as
routes.py: route definitions with AWS service integration stubs.
Handlers are thin; all business logic lives in the Lambda functions.

${...} placeholders are Terraform variable references interpolated
during make LAYER=03 apply. This file is not valid Python until after
interpolation.
"""

from typing import Any, Dict, List, Optional

from fastapi import Security
from fastapi_aws import APIKeyAuthorizer, AWSAPIRouter
from pydantic import BaseModel, Field

apikey_auth = APIKeyAuthorizer(authorizer_name="${apikey_authorizer_name}")

router = AWSAPIRouter()


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class WorkflowTemplateRequest(BaseModel):
    """Body for POST /workflows. Stores a named runfox YAML template."""

    name: str = Field(..., description="human-readable template name")
    spec: str = Field(..., description="runfox workflow YAML as a string")


class WorkflowRunRequest(BaseModel):
    """Body for POST /workflows/{workflow_id}/run. Supplies execution inputs."""

    inputs: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "workflow-level inputs passed to the runfox spec as the input context. "
            "Keys must match the input.FIELD references declared in the spec."
        ),
    )


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class WorkflowTemplateSummary(BaseModel):
    """One item in the template list response."""

    workflow_id: str
    name: str
    created_at: str


class WorkflowTemplateResponse(BaseModel):
    """Full template record returned by GET /workflows/{workflow_id}."""

    workflow_id: str
    name: str
    spec: str
    created_at: str


class WorkflowTemplateListResponse(BaseModel):
    templates: List[WorkflowTemplateSummary]


class WorkflowRunResponse(BaseModel):
    """Returned by POST /workflows/{workflow_id}/run."""

    workflow_id: str
    execution_id: str


class WorkflowStepProgress(BaseModel):
    """Count of steps in each status for a workflow execution."""

    ready: int = 0
    in_progress: int = 0
    complete: int = 0
    halted: int = 0
    retry: int = 0
    total: int = 0


class WorkflowExecutionResponse(BaseModel):
    """
    Returned by GET /workflows/{workflow_id}/executions/{execution_id}.

    progress is derived from WorkflowRecord.steps in runfox_state.
    outcome is null until the execution reaches a terminal status.
    """

    workflow_id: str
    execution_id: str
    status: str
    progress: WorkflowStepProgress
    created_at: str
    updated_at: str
    outcome: Optional[Any] = None


class WorkflowStepSummary(BaseModel):
    """
    One step entry in the steps list response.

    Returns the most recent run for each step. For the full retry
    history of a specific step use GET .../steps/{step_id}.

    If the step has not been dispatched yet (status READY, dependencies
    unmet) submitted_at and completed_at are null.
    """

    op: str
    step_id: str
    status: str
    run_id: int
    model_type: Optional[str] = None
    model_name: Optional[str] = None
    submitted_at: Optional[str] = None
    completed_at: Optional[str] = None


class WorkflowStepsResponse(BaseModel):
    steps: List[WorkflowStepSummary]


class WorkflowStepRun(BaseModel):
    """One dispatch attempt for a step."""

    run_id: int
    status: str
    model_type: str
    model_name: str
    submitted_at: str
    completed_at: Optional[str] = None
    output: Optional[Any] = None


class WorkflowStepResponse(BaseModel):
    """
    Returned by GET .../steps/{step_id}.

    runs contains all dispatch attempts in run_id order.
    op is the original user-supplied step label.
    step_id is md5(op).
    """

    op: str
    step_id: str
    runs: List[WorkflowStepRun]


# ---------------------------------------------------------------------------
# Template management
# ---------------------------------------------------------------------------


@router.post(
    "/",
    description="store a named runfox workflow template",
    response_model=WorkflowTemplateResponse,
    aws_lambda_arn="${workflow_api_lambda_arn}",
    aws_iam_arn="${workflow_api_lambda_iam_role_arn}"
)
async def create_workflow_template(
    body: WorkflowTemplateRequest,
    user=Security(apikey_auth),
):
    return


@router.get(
    "/",
    description="list workflow templates for the authenticated user",
    response_model=WorkflowTemplateListResponse,
    aws_lambda_arn="${workflow_api_lambda_arn}",
    aws_iam_arn="${workflow_api_lambda_iam_role_arn}",
)
async def list_workflow_templates(user=Security(apikey_auth)):
    return


@router.get(
    "/{workflow_id}",
    description="fetch a workflow template by id",
    response_model=WorkflowTemplateResponse,
    aws_lambda_arn="${workflow_api_lambda_arn}",
    aws_iam_arn="${workflow_api_lambda_iam_role_arn}",
)
async def get_workflow_template(workflow_id: str, user=Security(apikey_auth)):
    return


# ---------------------------------------------------------------------------
# Execution management
# ---------------------------------------------------------------------------


@router.post(
    "/{workflow_id}/run",
    description="submit a workflow execution with input values",
    response_model=WorkflowRunResponse,
    aws_lambda_arn="${workflow_api_lambda_arn}",
    aws_iam_arn="${workflow_api_lambda_iam_role_arn}",
)
async def run_workflow(
    workflow_id: str,
    body: WorkflowRunRequest,
    user=Security(apikey_auth),
):
    return


@router.get(
    "/{workflow_id}/executions/{execution_id}",
    description="get the status and outcome of a workflow execution",
    response_model=WorkflowExecutionResponse,
    aws_lambda_arn="${workflow_api_lambda_arn}",
    aws_iam_arn="${workflow_api_lambda_iam_role_arn}",
)
async def get_workflow_execution(
    workflow_id: str,
    execution_id: str,
    user=Security(apikey_auth),
):
    return


@router.delete(
    "/{workflow_id}/executions/{execution_id}",
    description="cancel an in-flight workflow execution",
    aws_lambda_arn="${workflow_api_lambda_arn}",
    aws_iam_arn="${workflow_api_lambda_iam_role_arn}",
)
async def cancel_workflow_execution(
    workflow_id: str,
    execution_id: str,
    user=Security(apikey_auth),
):
    return


# ---------------------------------------------------------------------------
# Step detail
# ---------------------------------------------------------------------------


@router.get(
    "/{workflow_id}/executions/{execution_id}/steps",
    description="list all steps for a workflow execution with their current status",
    response_model=WorkflowStepsResponse,
    aws_lambda_arn="${workflow_api_lambda_arn}",
    aws_iam_arn="${workflow_api_lambda_iam_role_arn}",
)
async def list_workflow_steps(
    workflow_id: str,
    execution_id: str,
    user=Security(apikey_auth),
):
    return


@router.get(
    "/{workflow_id}/executions/{execution_id}/steps/{step_id}",
    description=(
        "get full detail for one step including all retry attempts. "
        "step_id is the md5 of the step op label."
    ),
    response_model=WorkflowStepResponse,
    aws_lambda_arn="${workflow_api_lambda_arn}",
    aws_iam_arn="${workflow_api_lambda_iam_role_arn}",
)
async def get_workflow_step(
    workflow_id: str,
    execution_id: str,
    step_id: str,
    user=Security(apikey_auth),
):
    return
