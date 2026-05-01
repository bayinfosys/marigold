"""Model dispatch and SQS worker.

Every ECS task starts with the fixed command:
    python -c "from models import sqs_handler; sqs_handler()"

MODEL_TYPE selects the handler from _SPECS, which is populated by calling
load_all() before use. Call sites that need the full registry must call
load_all() explicitly -- importing this module alone does not trigger handler
imports.

Required environment variables (all tasks):
    MODEL_TYPE              task identifier (e.g. "instruct", "text-eval")
    MODELNAME               HuggingFace model identifier
    AWS_SQS_MODEL_QUEUE     SQS queue URL for this model
    RESULTS_TABLE           DynamoDB results cache table name
    SQS_VISIBILITY_TIMEOUT  matches the queue visibility_timeout_seconds (default 300)

Optional environment variables:
    IDLE_TIMEOUT            seconds to keep polling after queue goes empty (default 0)
    LOG_LEVEL               Python logging level (default INFO)
"""

import logging
import os

from shared.registry import BaseModelHandler, _SPECS  # noqa: F401

from models.worker import SQSWorker

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Registry population
# ---------------------------------------------------------------------------


def load_all():
    """Import all handler modules to populate shared.registry._SPECS.

    Must be called before any code that looks up _SPECS by model type.
    Importing this module alone does not trigger these imports.
    """
    from models import depth, image_embed, image_eval, image_text_eval  # noqa: F401
    from models import img2mask, img2txt, instruct, text_embed  # noqa: F401
    from models import text_eval, text_similarity, tts, txt2img  # noqa: F401
    from models import txt2audio  # noqa: F401
    from models import http  # noqa: F401


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def sqs_handler():
    """Fixed ECS task entry point for all model types."""
    load_all()

    model_type = os.environ["MODEL_TYPE"]
    modelname = os.environ["MODELNAME"]
    queue_url = os.environ["AWS_SQS_MODEL_QUEUE"]
    visibility_timeout = int(os.getenv("SQS_VISIBILITY_TIMEOUT", "300"))
    idle_timeout = int(os.getenv("IDLE_TIMEOUT", "0"))

    if model_type not in _SPECS:
        raise ValueError(
            "unknown MODEL_TYPE '%s'; registered types: %s"
            % (model_type, sorted(_SPECS))
        )

    spec = _SPECS[model_type]
    logger.info("loading '%s' for model '%s'", spec.handler_class.__name__, modelname)

    model = spec.handler_class(modelname)
    worker = SQSWorker(queue_url, model, visibility_timeout, idle_timeout)
    worker.run()
