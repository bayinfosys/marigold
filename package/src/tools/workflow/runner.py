"""
workflow/runner.py -- Marigold SQS runner configuration.

Provides the queue_url callable and message_body_fn for SQSRunner.
These encode Marigold-specific routing and message format conventions;
they have no place in the runfox library.

queue_url_fn    routes by model_type from job.inputs
message_body_fn strips control fields, renders prompt templates,
                and adds the WORKFLOW# message_id
"""

from hashlib import md5

from runfox.results import DispatchJob
from shared.sqs_models import MarigoldSQSMessage


def make_queue_url_fn(queue_map: dict):
    """
    Return a queue_url callable that routes by model_type.

    queue_map is {model_type: queue_url}. Raises ValueError for
    unknown model types so misconfigured steps fail loudly.
    """

    def queue_url_fn(job: DispatchJob) -> str:
        # model_type = job.inputs.get("model_type")
        model_name = job.inputs.get("model_name")
        if not model_name:
            return None

        model_md5 = md5(model_name.encode()).hexdigest()
        url = queue_map.get(model_md5)
        if url is None:
            raise ValueError(
                f"No queue configured for model_name {model_name!r}. "
                f"Available: {list(queue_map)}"
            )
        return url

    return queue_url_fn


def make_message_body_fn(user_id: str):
    """
    Build the SQS message body for a Marigold workflow step.

    - Strips model_type (used for routing, not needed by the worker)
    - Retains model_name (worker needs it to load the correct model)
    - Renders prompt_template into prompt if present
    - Adds WORKFLOW# message_id for result routing

    NB: the outer function injects the user_id into the inner from the backend context
    """
    def marigold_message_body(job: DispatchJob, workflow_execution_id: str) -> dict:
        inputs = dict(job.inputs)
        model_type = inputs["model_type"]
        model_name = inputs["model_name"]
        model_inputs = inputs.get("model_inputs", {})
        prompt_template = inputs.get("prompt_template")

        if prompt_template is not None:
            template_vars = {
                k: v for k, v in model_inputs.items()
                if "{" + k + "}" in prompt_template
            }
            model_inputs = {
                **model_inputs,
                "prompt": prompt_template.format(**template_vars),
            }

        msg = MarigoldSQSMessage(
            user_id=user_id,
            message_id=f"WORKFLOW#{workflow_execution_id}#{job.op}#{job.run_id}",
            model_type=model_type,
            model_name=model_name,
            model_inputs=model_inputs,
            workflow_execution_id=workflow_execution_id,
            op=job.op,
            run_id=job.run_id,
        )
        return msg.model_dump()

    return marigold_message_body
