"""Local workflow executor.

Maps (fn, inputs) to a model handler _run() call.
For model_type 'dummy', returns inputs unchanged (echo behaviour).
For real model types, loads the handler from the registry.
"""

import logging
import os
import models
from shared.registry import _SPECS


log = logging.getLogger(__name__)
log.setLevel(logging.INFO)

_SKIP_FIELDS = {"model_type", "model_name"}


def execute(op: str, inputs: dict) -> dict:
    """Execute one workflow step locally.

    fn      -- model_type value from the step input dict
    inputs  -- fully resolved step inputs

    Returns an output dict.
    """
    model_type = inputs.get("model_type", op)
    model_name = inputs.get("model_name", "")

    if model_type == "dummy":
        return {k: v for k, v in inputs.items() if k not in _SKIP_FIELDS}

    return _execute_model(model_type, model_name, inputs)


def _execute_model(model_type: str, model_name: str, inputs: dict) -> dict:
    import models
    from shared.registry import _SPECS

    models.load_all()

    if model_type not in _SPECS:
        raise ValueError("unknown model_type '%s'" % model_type)

    spec = _SPECS[model_type]
    handler = spec.handler_class(model_name)

    payload = {k: v for k, v in inputs.items() if k not in _SKIP_FIELDS}
    payload["model"] = model_name

    # instruct models expect a messages list, not a flat message field
    if model_type == "instruct" and "message" in payload:
        payload["messages"] = [{"role": "user", "content": payload.pop("message")}]

    try:
        result = handler.process(
            user_id="workflow-local",
            message_id="workflow-local-test",
            request=payload,
        )

        return result.model_dump() if hasattr(result, "model_dump") else result
    except Exception as e:
        log.error("model execution failed [%s/%s]: %s", model_type, model_name, e)
        raise
