"""Image-to-text: captioning, OCR, visual question answering.

Takes an image (base64) and an optional text prompt, returns generated text.

The request uses the Img2TxtRequest format. Clients submit a base64 image
in the input field and an optional prompt. A minimal request with no prompt
uses the DEFAULT_PROMPT below.

Compatible models:
    any AutoProcessor + AutoModelForVision2Seq (LLaVA, Idefics, PaliGemma, etc.)
"""

import logging
import os
from time import perf_counter as clock

import torch
from api.models import Img2TxtRequest, Img2TxtResponse
from models.standard_loader import ModelLoaderResult, standard_loader
from shared.enums import ModelMode, ModelType
from shared.models import InstructMessage, InstructRole
from shared.outputs import decode_image
from shared.registry import BaseModelHandler, model_spec
from shared.usage import build_usage
from transformers import set_seed

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

DEFAULT_PROMPT = "Describe this image."


def load_img2txt(modelname: str, cache_dir: str = None, **kwargs) -> ModelLoaderResult:
    """Image-to-text: captioning, OCR, VQA."""
    from transformers import AutoModelForVision2Seq as M
    from transformers import AutoProcessor as T

    return standard_loader(T, M, modelname, cache_dir=cache_dir, **kwargs)


def _build_hf_prompt(request: Img2TxtRequest) -> tuple:
    """Extract images and build a HuggingFace-compatible prompt list from the request.

    Returns (hf_prompt, images) where hf_prompt is the list passed to
    processor.apply_chat_template and images is the list of PIL Images.
    """
    prompt_text = request.prompt or DEFAULT_PROMPT

    try:
        image = decode_image(request.input)
    except Exception as e:
        logger.error("failed to decode image input [%s]", str(e))
        raise ValueError("invalid image input") from e

    hf_prompt = [
        {
            "role": "user",
            "content": [
                {"type": "image"},
                {"type": "text", "text": prompt_text},
            ],
        }
    ]

    return hf_prompt, [image]


@model_spec(
    model_type=ModelType.IMG2TXT,
    mode=ModelMode.GEN,
    output_fields=[],
    loader=load_img2txt,
    request_model=Img2TxtRequest,
    response_model=Img2TxtResponse,
    route="/gen/img2txt",
)
class Img2TxtModel(BaseModelHandler):

    def __init__(self, modelname: str):
        super().__init__(modelname)

    def _run(
        self, user_id: str, message_id: str, request: Img2TxtRequest
    ) -> Img2TxtResponse:
        T = clock()

        hf_prompt, images = _build_hf_prompt(request)

        logger.info("[%s/%s] prompt: '%s'", user_id, message_id, hf_prompt)

        try:
            prompt_str = self.processor.apply_chat_template(
                hf_prompt,
                return_tensors=None,
                tokenize=False,
                add_generation_prompt=True,
            )
        except Exception as e:
            logger.exception(
                "[%s/%s] apply_chat_template failed [%s]", user_id, message_id, str(e)
            )
            raise

        model_inputs = self.processor(
            text=prompt_str,
            images=images,
            return_tensors="pt",
        )

        if request.seed:
            set_seed(request.seed)

        T1 = clock()
        with torch.no_grad():
            model_outputs = self.model.generate(
                **model_inputs,
                max_new_tokens=request.max_tokens,
            )
        iduration = clock() - T1

        generated_ids = [
            output_ids[len(input_ids):]
            for input_ids, output_ids in zip(model_inputs.input_ids, model_outputs)
        ]

        outputs = self.processor.batch_decode(generated_ids, skip_special_tokens=True)

        input_tokens = model_inputs.input_ids.nelement()
        output_tokens = sum(x.nelement() for x in generated_ids)
        duration = clock() - T

        logger.info(
            "[%s/%s] '%s' %i tokens [in=%i out=%i] in %0.2fs",
            user_id,
            message_id,
            self.modelname,
            input_tokens + output_tokens,
            input_tokens,
            output_tokens,
            duration,
        )

        usage = build_usage(
            user_id=user_id,
            model_type=ModelType.IMG2TXT,
            modelname=self.modelname,
            duration=duration,
            inference=iduration,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            load_time_ms=self.load_time_ms,
            model_size_bytes=self.model_size_bytes,
        )

        return Img2TxtResponse(
            model=self.modelname,
            choices=[InstructMessage(role=InstructRole.ASSISTANT, content=outputs[0])],
            usage=usage,
        )
