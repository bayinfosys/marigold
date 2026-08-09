"""
workflow/api_handler.py -- Workflow API Lambda.

Handles all HTTP-facing workflow routes via API Gateway proxy integration:

    POST   /workflows
    GET    /workflows
    GET    /workflows/{workflow_id}
    POST   /workflows/{workflow_id}/run
    GET    /workflows/{workflow_id}/executions/{execution_id}
    DELETE /workflows/{workflow_id}/executions/{execution_id}
    GET    /workflows/{workflow_id}/executions/{execution_id}/steps
    GET    /workflows/{workflow_id}/executions/{execution_id}/steps/{step_id}

Routing is on event["resource"] (the API Gateway resource template string
with {param} placeholders), which matches the route definitions in
api/workflow/routes.py exactly.

Environment variables
---------------------
WORKFLOW_TEMPLATE_TABLE     DynamoDB table for WorkflowTemplate records
WORKFLOW_STATE_TABLE        DynamoDB table for WorkflowExecution records
WORKFLOW_STEPS_TABLE        DynamoDB table for WorkflowStep records
WORKFLOW_TASKS_TABLE        DynamoDB table for runfox SQSRunner tasks
AWS_S3_ASSETS_BUCKET_NAME   S3 bucket containing models_config.json
MODELS_CONFIG_S3_OBJECT     S3 key for models_config.json
QUEUE_URL_DUMMY             SQS queue URL for the dummy model

FIXME (aws-removal): this whole file is API Gateway proxy-integration
shaped (event["resource"], event["httpMethod"], mk_resp building a
raw {"statusCode": ..., "body": ...} dict). Once integrated with the
rest of Marigold's API, this probably becomes a set of FastAPI routes
using APIRouter like gen.py/users.py/etc, rather than a router dict
matched by hand -- get_userid_from_event/mk_resp were doing the job
auth.py's apikey_auth Security dependency and FastAPI's own response
model already do elsewhere in this codebase.

get_userid_from_event/mk_resp come from shared/lambda_proxy.py, which
travels with this package for now (it's the workflow branch's own
dependency, not deleted -- see the note in the earlier review).
"""

import hashlib
import json
import logging
import os
from datetime import datetime, timezone

import runfox as rfx
import yaml
from runfox.results import Complete, Dispatch, Halt
from shared.lambda_proxy import get_userid_from_event, mk_resp

from .models import (WorkflowExecution, WorkflowStep, WorkflowTemplate,
                     parse_workflow_execution_id)
from .runner import make_message_body_fn, make_queue_url_fn

logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))

template_table = os.environ.get("WORKFLOW_TEMPLATE_TABLE", "")
state_table = os.environ.get("WORKFLOW_STATE_TABLE", "")
steps_table = os.environ.get("WORKFLOW_STEPS_TABLE", "")

# TODO: inject a dynawrap DBBackend rather than constructing one here.
_dynawrap = None


def _load_queue_map() -> dict:
    # TODO: build this from models.catalogue / models.yaml instead of
    # an S3-hosted models_config.json. Identical duplicate of this
    # function exists in executor.py -- fix both or collapse to one.
    dummy_name = "dummy"
    dummy_md5 = hashlib.md5(dummy_name.encode()).hexdigest()
    return {dummy_md5: os.environ.get("QUEUE_URL_DUMMY", "")}


QUEUE_MAP = _load_queue_map()


def _make_backend(user_id: str) -> rfx.Backend:
    """Construct a runfox Backend for workflow state management.

    FIXME (aws-removal): SQSRunner/DynamoDBStore removed -- unreachable
    until runfox has non-AWS Store/Runner implementations. See the
    same FIXME in executor.py.
    """
    logger.warning("no local runfox backend implemented yet")
    return None


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _path_params(event: dict) -> dict:
    return event.get("pathParameters") or {}


def _body(event: dict) -> dict:
    raw = event.get("body") or "{}"
    if isinstance(raw, str):
        return json.loads(raw)
    return raw


# ---------------------------------------------------------------------------
# Template handlers
# ---------------------------------------------------------------------------


def handle_create_template(user_id: str, event: dict) -> dict:
    body = _body(event)
    name = body.get("name")
    spec = body.get("spec")

    if not name or not spec:
        return mk_resp(400, {"message": "name and spec are required"})

    try:
        yaml.safe_load(spec)
    except yaml.YAMLError as e:
        return mk_resp(400, {"message": f"invalid YAML: {e}"})

    spec_dict = yaml.safe_load(spec)
    workflow_id = hashlib.md5(
        json.dumps(spec_dict, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    now = _now()
    record = WorkflowTemplate(
        user_id=user_id,
        workflow_id=workflow_id,
        name=name,
        spec=spec,
        created_at=now,
    )

    # FIXME: _dynawrap is None until injected.
    _dynawrap.save(template_table, record)

    return mk_resp(
        200,
        {
            "workflow_id": workflow_id,
            "name": name,
            "spec": spec,
            "created_at": now,
        },
    )


def handle_list_templates(user_id: str, event: dict) -> dict:
    # FIXME: _dynawrap is None until injected.
    items = list(_dynawrap.query(template_table, WorkflowTemplate, user_id=user_id))

    return mk_resp(
        200,
        {
            "templates": [
                {
                    "workflow_id": item.workflow_id,
                    "name": item.name,
                    "created_at": item.created_at,
                }
                for item in items
            ]
        },
    )


def handle_get_template(user_id: str, event: dict) -> dict:
    workflow_id = _path_params(event)["workflow_id"]

    # FIXME: _dynawrap is None until injected.
    item = _dynawrap.get(
        template_table, WorkflowTemplate, user_id=user_id, workflow_id=workflow_id
    )
    if item is None:
        return mk_resp(404, {"message": "template not found"})

    return mk_resp(
        200,
        {
            "workflow_id": item.workflow_id,
            "name": item.name,
            "spec": item.spec,
            "created_at": item.created_at,
        },
    )


# ---------------------------------------------------------------------------
# Execution handlers
# ---------------------------------------------------------------------------


def handle_run_workflow(user_id: str, event: dict) -> dict:
    workflow_id = _path_params(event)["workflow_id"]
    body = _body(event)
    inputs = body.get("inputs", {})

    # FIXME: _dynawrap is None until injected.
    template = _dynawrap.get(
        template_table, WorkflowTemplate, user_id=user_id, workflow_id=workflow_id
    )
    if template is None:
        return mk_resp(404, {"message": "template not found"})

    backend = _make_backend(user_id)

    wf = rfx.Workflow.from_yaml(template.spec, backend, inputs=inputs)

    workflow_execution_id = wf.id
    _, execution_id = parse_workflow_execution_id(workflow_execution_id)

    now = _now()
    execution = WorkflowExecution(
        user_id=user_id,
        workflow_id=workflow_id,
        execution_id=execution_id,
        status="in_progress",
        runfox_state=json.dumps(backend.load(workflow_execution_id).to_dict()),
        created_at=now,
        updated_at=now,
    )
    _dynawrap.save(state_table, execution)

    result = wf.advance()

    if isinstance(result, Dispatch):
        try:
            backend.dispatch(wf.id, result.jobs)
        except (KeyError, ValueError) as e:
            # Spec is malformed -- a required step input field is missing.
            # Mark the execution record as cancelled to avoid leaving it
            # stranded as in_progress, then return a 400.
            cancelled = execution.model_copy(
                update={"status": "cancelled", "updated_at": _now()}
            )
            _dynawrap.save(state_table, cancelled)
            logger.warning(
                "workflow_execution_id=%s dispatch failed, spec invalid: %s",
                workflow_execution_id,
                str(e),
            )
            return mk_resp(400, {"message": f"invalid workflow spec: {e}"})
        logger.info(
            "workflow_execution_id=%s dispatched %d initial jobs",
            workflow_execution_id,
            len(result.jobs),
        )
    elif isinstance(result, Complete):
        updated = execution.model_copy(
            update={
                "status": "complete",
                "outcome": json.dumps(result.outcome),
                "updated_at": _now(),
            }
        )
        _dynawrap.save(state_table, updated)
    elif isinstance(result, Halt):
        updated = execution.model_copy(
            update={
                "status": "halted",
                "outcome": json.dumps(result.result),
                "updated_at": _now(),
            }
        )
        _dynawrap.save(state_table, updated)

    return mk_resp(
        200,
        {
            "workflow_id": workflow_id,
            "execution_id": execution_id,
        },
    )


def handle_get_execution(user_id: str, event: dict) -> dict:
    params = _path_params(event)
    workflow_id = params["workflow_id"]
    execution_id = params["execution_id"]

    # FIXME: _dynawrap is None until injected.
    execution = _dynawrap.get(
        state_table,
        WorkflowExecution,
        user_id=user_id,
        workflow_id=workflow_id,
        execution_id=execution_id,
    )
    if execution is None:
        return mk_resp(404, {"message": "execution not found"})

    record = execution.get_workflow_record()
    progress = {
        "ready": sum(1 for s in record.steps.values() if s.status.value == "ready"),
        "in_progress": sum(
            1 for s in record.steps.values() if s.status.value == "in_progress"
        ),
        "complete": sum(
            1 for s in record.steps.values() if s.status.value == "complete"
        ),
        "halted": sum(1 for s in record.steps.values() if s.status.value == "halted"),
        "retry": sum(1 for s in record.steps.values() if s.status.value == "retry"),
        "total": len(record.steps),
    }

    return mk_resp(
        200,
        {
            "workflow_id": execution.workflow_id,
            "execution_id": execution.execution_id,
            "status": execution.status,
            "progress": progress,
            "created_at": execution.created_at,
            "updated_at": execution.updated_at,
            "outcome": json.loads(execution.outcome) if execution.outcome else None,
        },
    )


def handle_cancel_execution(user_id: str, event: dict) -> dict:
    params = _path_params(event)
    workflow_id = params["workflow_id"]
    execution_id = params["execution_id"]

    # FIXME: _dynawrap is None until injected.
    execution = _dynawrap.get(
        state_table,
        WorkflowExecution,
        user_id=user_id,
        workflow_id=workflow_id,
        execution_id=execution_id,
    )
    if execution is None:
        return mk_resp(404, {"message": "execution not found"})

    if execution.status in ("complete", "halted", "cancelled"):
        return mk_resp(409, {"message": f"execution is already {execution.status}"})

    updated = execution.model_copy(
        update={
            "status": "cancelled",
            "updated_at": _now(),
        }
    )
    _dynawrap.save(state_table, updated)

    return mk_resp(200, {"message": "cancelled"})


# ---------------------------------------------------------------------------
# Step detail handlers
# ---------------------------------------------------------------------------


def handle_list_steps(user_id: str, event: dict) -> dict:
    params = _path_params(event)
    workflow_id = params["workflow_id"]
    execution_id = params["execution_id"]

    # FIXME: _dynawrap is None until injected.
    items = list(
        _dynawrap.query(
            steps_table,
            WorkflowStep,
            user_id=user_id,
            workflow_id=workflow_id,
            execution_id=execution_id,
        )
    )

    latest: dict[str, WorkflowStep] = {}
    for item in items:
        existing = latest.get(item.step_id)
        if existing is None or item.run_id > existing.run_id:
            latest[item.step_id] = item

    return mk_resp(
        200,
        {
            "steps": [
                {
                    "op": item.op,
                    "step_id": item.step_id,
                    "status": item.status,
                    "run_id": item.run_id,
                    "model_type": item.model_type,
                    "model_name": item.model_name,
                    "submitted_at": item.submitted_at,
                    "completed_at": item.completed_at,
                }
                for item in latest.values()
            ]
        },
    )


def handle_get_step(user_id: str, event: dict) -> dict:
    params = _path_params(event)
    workflow_id = params["workflow_id"]
    execution_id = params["execution_id"]
    sid = params["step_id"]

    # FIXME: _dynawrap is None until injected.
    items = list(
        _dynawrap.query(
            steps_table,
            WorkflowStep,
            user_id=user_id,
            workflow_id=workflow_id,
            execution_id=execution_id,
            step_id=sid,
        )
    )

    if not items:
        return mk_resp(404, {"message": "step not found"})

    items_sorted = sorted(items, key=lambda x: x.run_id)
    op = items_sorted[0].op

    return mk_resp(
        200,
        {
            "op": op,
            "step_id": sid,
            "runs": [
                {
                    "run_id": item.run_id,
                    "status": item.status,
                    "model_type": item.model_type,
                    "model_name": item.model_name,
                    "submitted_at": item.submitted_at,
                    "completed_at": item.completed_at,
                    "output": json.loads(item.output) if item.output else None,
                }
                for item in items_sorted
            ],
        },
    )


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


_ROUTES = {
    ("POST", "/workflows"): handle_create_template,
    ("GET", "/workflows"): handle_list_templates,
    ("GET", "/workflows/{workflow_id}"): handle_get_template,
    ("POST", "/workflows/{workflow_id}/run"): handle_run_workflow,
    ("GET", "/workflows/{workflow_id}/executions/{execution_id}"): handle_get_execution,
    (
        "DELETE",
        "/workflows/{workflow_id}/executions/{execution_id}",
    ): handle_cancel_execution,
    (
        "GET",
        "/workflows/{workflow_id}/executions/{execution_id}/steps",
    ): handle_list_steps,
    (
        "GET",
        "/workflows/{workflow_id}/executions/{execution_id}/steps/{step_id}",
    ): handle_get_step,
}


def handler(event, context):
    method = event.get("httpMethod", "")
    resource = event.get("resource", "")

    logger.info("method=%s resource=%s", method, resource)

    try:
        user_id = get_userid_from_event(event)
    except RuntimeError as e:
        logger.error("auth error: %s", e)
        return mk_resp(401, {"message": "unauthorised"})

    fn = _ROUTES.get((method, resource))
    if fn is None:
        return mk_resp(404, {"message": "route not found"})

    try:
        return fn(user_id, event)
    except Exception:
        logger.exception("unhandled error method=%s resource=%s", method, resource)
        return mk_resp(500, {"message": "internal error"})
