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
import sys

from models.worker import SQSWorker
from shared.registry import _SPECS, BaseModelHandler  # noqa: F401

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Registry population
# ---------------------------------------------------------------------------


def load_all():
    """Import all handler modules to populate shared.registry._SPECS.

    Must be called before any code that looks up _SPECS by model type.
    Importing this module alone does not trigger these imports.
    """
    from models import http  # noqa: F401
    from models import txt2audio  # noqa: F401
    from models import (depth, image_embed, image_eval,  # noqa: F401
                        image_text_eval, img2mask, img2txt, instruct,
                        text_embed, text_eval, text_similarity, tts, txt2img)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def sqs_handler():
    """Fixed ECS task entry point for all model types.
    NB: if model load fails, we exit, queues are per-model, so one model load fail means all model loads will fail
    NB: we always exit cleanly (retval 0) to prevent ECS restarting the containers and getting stuck in a forever loop
    """
    load_all()

    model_type = os.environ["MODEL_TYPE"]
    model_hash = os.environ["MODEL_HASH"]
    modelname = os.environ["MODELNAME"]
    queue_url = os.environ["AWS_SQS_MODEL_QUEUE"]
    visibility_timeout = int(os.getenv("SQS_VISIBILITY_TIMEOUT", "300"))

    if model_type not in _SPECS:
        logger.error(
            "unknown MODEL_TYPE '%s'; registered types: %s",
            model_type,
            sorted(_SPECS),
        )
        sys.exit(0)

    spec = _SPECS[model_type]
    logger.info("loading '%s' for model '%s'", spec.handler_class.__name__, modelname)

    try:
        model = spec.handler_class(modelname)
    except Exception as e:
        logger.exception(
            "fatal: failed to load '%s' for model '%s': %s -- exiting",
            spec.handler_class.__name__,
            modelname,
            e,
        )
        sys.exit(0)

    worker = SQSWorker(queue_url, model, visibility_timeout, model_hash=model_hash)
    worker.run()
