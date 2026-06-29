"""Observation-to-action: vision-language-action (VLA) robot policy inference.

Takes an RGB observation image and a natural language task instruction and
returns the model's raw generated output. Action decoding, unnormalisation,
and trajectory construction are workflow or client responsibilities.

For OpenVLA-family models the raw output is a sequence of action tokens.
The client or a downstream workflow step decodes these using the per-dataset
normalisation statistics that ship alongside the model weights.

Prompt configuration (models.yaml extra_env):

    PROMPT_TEMPLATE     format string with {instruction} placeholder.
                        Default matches the OpenVLA training prompt.

Proprioceptive state:
    When request.state is provided and PROPRIOCEPTION_MODE=text (default),
    the state vector is appended to the instruction as a text string before
    substitution into the prompt template. Set PROPRIOCEPTION_MODE=none to
    discard state.

Compatible models (non-exhaustive):
    openvla/openvla-7b
    openvla/openvla-oft-7b
    (any VLA model using AutoProcessor + AutoModelForVision2Seq)
"""

import logging
import os
from time import perf_counter as clock
from typing import List, Optional

import torch

from api.models import Obs2ActRequest, Obs2ActResponse
from models.standard_loader import ModelLoaderResult, standard_loader
from shared.enums import ModelMode, ModelType
from shared.models import InstructMessage, InstructRole
from shared.outputs import decode_image
from shared.registry import BaseModelHandler, model_spec
from shared.usage import build_usage
from transformers import set_seed

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

_DEFAULT_PROMPT_TEMPLATE = (
    "In: What action should the robot take to {instruction}?\nOut:"
)
_DEFAULT_ACTION_DIM  = 7
_VALID_PROPR_MODES   = {"text", "none"}


def load_obs2act(modelname: str, cache_dir: str = None, **kwargs) -> ModelLoaderResult:
    """VLA policy via AutoProcessor + AutoModelForVision2Seq."""
    from transformers import AutoModelForVision2Seq as M
    from transformers import AutoProcessor as T

    return standard_loader(T, M, modelname, cache_dir=cache_dir, **kwargs)


def _build_prompt(
    instruction: str,
    state: Optional[List[float]],
    template: str,
    proprioception_mode: str,
) -> str:
    """Substitute instruction and optional state into the prompt template.

    In text proprioception mode the state vector is appended to the
    instruction before substitution. This is the only transformation
    applied at the handler level; all action decoding is downstream.
    """
    if state and proprioception_mode == "text":
        state_str = "[" + ", ".join("%.4f" % v for v in state) + "]"
        full_instruction = "%s. Current state: %s" % (instruction, state_str)
    else:
        full_instruction = instruction

    return template.format(instruction=full_instruction)


@model_spec(
    model_type     = ModelType.OBS2ACT,
    mode           = ModelMode.GEN,
    output_fields  = [],
    loader         = load_obs2act,
    request_model  = Obs2ActRequest,
    response_model = Obs2ActResponse,
    route          = "/gen/obs2act",
)
class Obs2ActModel(BaseModelHandler):

    def __init__(self, modelname: str):
        super().__init__(modelname)

        self.action_dim      = int(os.getenv("ACTION_DIM", str(_DEFAULT_ACTION_DIM)))
        self.prompt_template = os.getenv("PROMPT_TEMPLATE", _DEFAULT_PROMPT_TEMPLATE)
        self.propr_mode      = os.getenv("PROPRIOCEPTION_MODE", "text")

        if self.propr_mode not in _VALID_PROPR_MODES:
            logger.warning(
                "'%s' unrecognised PROPRIOCEPTION_MODE='%s', falling back to 'text'",
                modelname, self.propr_mode,
            )
            self.propr_mode = "text"

        logger.info(
            "'%s' action_dim=%i propr_mode=%s",
            modelname, self.action_dim, self.propr_mode,
        )

    def _run(
        self, user_id: str, message_id: str, request: Obs2ActRequest
    ) -> Obs2ActResponse:

        T = clock()

        try:
            image = decode_image(request.image)
        except Exception as e:
            logger.error("[%s/%s] image decode failed: %s", user_id, message_id, e)
            raise ValueError("could not decode observation image") from e

        prompt = _build_prompt(
            request.instruction,
            request.state,
            self.prompt_template,
            self.propr_mode,
        )

        logger.info(
            "[%s/%s] obs2act: instruction='%s' state=%s",
            user_id, message_id,
            request.instruction[:80],
            "yes" if request.state else "no",
        )

        model_inputs = self.processor(
            text=prompt,
            images=image,
            return_tensors="pt",
        )

        if request.seed is not None:
            set_seed(request.seed)

        T1 = clock()
        with torch.no_grad():
            output_ids = self.model.generate(
                **model_inputs,
                max_new_tokens=self.action_dim,
                do_sample=False,
            )
        iduration = clock() - T1

        input_len     = model_inputs.input_ids.shape[1]
        generated_ids = [output_ids[0][input_len:]]

        output_text = self.processor.batch_decode(
            generated_ids, skip_special_tokens=False
        )[0]

        input_tokens  = model_inputs.input_ids.nelement()
        output_tokens = generated_ids[0].nelement()
        duration      = clock() - T

        logger.info(
            "[%s/%s] '%s' raw output='%s' in %0.2fs (inference %0.2fs)",
            user_id, message_id, self.modelname,
            repr(output_text[:80]),
            duration, iduration,
        )

        usage = build_usage(
            user_id          = user_id,
            model_type       = ModelType.OBS2ACT,
            modelname        = self.modelname,
            duration         = duration,
            inference        = iduration,
            input_tokens     = input_tokens,
            output_tokens    = output_tokens,
            load_time_ms     = self.load_time_ms,
            model_size_bytes = self.model_size_bytes,
        )

        return Obs2ActResponse(
            model   = self.modelname,
            choices = [InstructMessage(role=InstructRole.ASSISTANT, content=output_text)],
            usage   = usage,
        )
