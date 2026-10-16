"""Model handler registry population.

MODEL_TYPE values map to handlers through shared.registry._SPECS, which
is populated by calling load_all(). Call sites that need the full
registry -- the worker, the cache container -- call load_all()
explicitly; importing this module alone does not import any handler.

The worker's entry point is models.entrypoint_handlers.local_handler.
"""

import logging

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
    from models import asr  # noqa: F401
    from models import (depth, image_embed, image_eval,  # noqa: F401
                        image_text_eval, img2mask, img2txt, img2vid,
                        instruct, text_embed, text_eval, text_similarity,
                        tts, txt2img, txt2vid)
