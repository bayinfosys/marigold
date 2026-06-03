"""Video-to-text: captioning, temporal description, visual question answering.

Takes a video input and returns generated text. Frames are sampled uniformly
from the video and passed to a vision-language model.

Two input modes are supported, selected via the INPUT_MODE env var in
models.yaml extra_env:

    INPUT_MODE=image_frames  (default)
        Sampled frames are passed as a list of images. The chat template
        receives one {"type": "image"} token per frame. Works with any
        model that accepts multi-image input, including LLaVA-OneVision,
        InternVL2, and Idefics3.

    INPUT_MODE=video
        Frames are passed as a single video sequence. The chat template
        receives one {"type": "video"} token. Required for models with
        native video encoders such as Qwen2-VL and InternVideo2-Chat.

The number of sampled frames is controlled by the MAX_FRAMES env var,
defaulting to 8. Models with short context windows (InternVL2-2B) should
use 4-8 frames. Models with longer context (Qwen2-VL-72B) can handle 32+.

Compatible models (non-exhaustive):
    llava-hf/llava-onevision-qwen2-7b-ov-hf    INPUT_MODE=image_frames
    OpenGVLab/InternVL2-8B                      INPUT_MODE=image_frames
    HuggingFaceM4/idefics3-8b-llama3            INPUT_MODE=image_frames
    Qwen/Qwen2-VL-7B-Instruct                   INPUT_MODE=video
    DAMO-NLP-SG/Video-LLaMA-2-7B-Finetuned      INPUT_MODE=video
"""

import logging
import os
from time import perf_counter as clock

import torch

from api.models import Vid2TxtRequest, Vid2TxtResponse
from models.standard_loader import ModelLoaderResult, standard_loader
from shared.enums import ModelMode, ModelType
from shared.models import InstructMessage, InstructRole
from shared.outputs import decode_video_frames
from shared.registry import BaseModelHandler, model_spec
from shared.usage import record_usage
from transformers import set_seed

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

DEFAULT_PROMPT     = "Describe what happens in this video."
_VALID_INPUT_MODES = {"image_frames", "video"}


def load_vid2txt(modelname: str, cache_dir: str = None, **kwargs) -> ModelLoaderResult:
    """Video-to-text via AutoProcessor + AutoModelForVision2Seq.

    The same model class covers image and video vision-language models in
    transformers. Video-specific behaviour is handled at inference time via
    the processor's chat template and the INPUT_MODE env var.
    """
    from transformers import AutoModelForVision2Seq as M
    from transformers import AutoProcessor as T

    return standard_loader(T, M, modelname, cache_dir=cache_dir, **kwargs)


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def _build_prompt_image_frames(frames: list, prompt_text: str) -> tuple:
    """Build a chat template and inputs for image_frames mode.

    Returns (hf_prompt, processor_kwargs) where hf_prompt is passed to
    apply_chat_template and processor_kwargs is merged into the processor call.
    One {"type": "image"} token is inserted per frame before the text prompt.
    """
    hf_prompt = [
        {
            "role": "user",
            "content": (
                [{"type": "image"} for _ in frames]
                + [{"type": "text", "text": prompt_text}]
            ),
        }
    ]
    processor_kwargs = {"images": frames}
    return hf_prompt, processor_kwargs


def _build_prompt_video(frames: list, prompt_text: str) -> tuple:
    """Build a chat template and inputs for video mode.

    Returns (hf_prompt, processor_kwargs) where hf_prompt contains a single
    {"type": "video"} token and processor_kwargs passes frames as a single
    video sequence. For models such as Qwen2-VL that have a native video
    encoder and expect frames as a list under the videos kwarg.
    """
    hf_prompt = [
        {
            "role": "user",
            "content": [
                {"type": "video"},
                {"type": "text", "text": prompt_text},
            ],
        }
    ]
    processor_kwargs = {"videos": [frames]}
    return hf_prompt, processor_kwargs


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


@model_spec(
    model_type     = ModelType.VID2TXT,
    mode           = ModelMode.GEN,
    output_fields  = [],
    loader         = load_vid2txt,
    request_model  = Vid2TxtRequest,
    response_model = Vid2TxtResponse,
    route          = "/gen/vid2txt",
)
class Vid2TxtModel(BaseModelHandler):

    def __init__(self, modelname: str):
        super().__init__(modelname)
        self.max_frames = int(os.getenv("MAX_FRAMES", "8"))
        self.input_mode = os.getenv("INPUT_MODE", "image_frames")

        if self.input_mode not in _VALID_INPUT_MODES:
            logger.warning(
                "'%s' unrecognised INPUT_MODE='%s', falling back to 'image_frames'",
                modelname, self.input_mode,
            )
            self.input_mode = "image_frames"

        logger.info(
            "'%s' max_frames=%i input_mode=%s",
            modelname, self.max_frames, self.input_mode,
        )

    def _run(
        self, user_id: str, message_id: str, request: Vid2TxtRequest
    ) -> Vid2TxtResponse:

        T = clock()

        try:
            frames = decode_video_frames(request.input, self.max_frames)
        except (ValueError, RuntimeError) as e:
            logger.error("[%s/%s] video decode failed: %s", user_id, message_id, e)
            raise

        logger.info(
            "[%s/%s] decoded %i frames with '%s'",
            user_id, message_id, len(frames), self.modelname,
        )

        prompt_text = request.prompt or DEFAULT_PROMPT

        if self.input_mode == "image_frames":
            hf_prompt, processor_kwargs = _build_prompt_image_frames(frames, prompt_text)
        else:
            hf_prompt, processor_kwargs = _build_prompt_video(frames, prompt_text)

        try:
            prompt_str = self.processor.apply_chat_template(
                hf_prompt,
                tokenize=False,
                add_generation_prompt=True,
            )
        except Exception as e:
            logger.exception(
                "[%s/%s] apply_chat_template failed: %s", user_id, message_id, e
            )
            raise

        model_inputs = self.processor(
            text=prompt_str,
            return_tensors="pt",
            **processor_kwargs,
        )

        if request.seed is not None:
            set_seed(request.seed)

        T1 = clock()
        with torch.no_grad():
            output_ids = self.model.generate(
                **model_inputs,
                max_new_tokens=request.max_tokens,
            )
        iduration = clock() - T1

        generated_ids = [
            out[len(inp):]
            for inp, out in zip(model_inputs.input_ids, output_ids)
        ]
        outputs = self.processor.batch_decode(
            generated_ids, skip_special_tokens=True
        )

        input_tokens  = model_inputs.input_ids.nelement()
        output_tokens = sum(x.nelement() for x in generated_ids)
        duration      = clock() - T

        logger.info(
            "[%s/%s] '%s' %i frames -> %i tokens in %0.2fs (inference %0.2fs)",
            user_id, message_id, self.modelname,
            len(frames), output_tokens, duration, iduration,
        )

        usage = record_usage(
            user_id          = user_id,
            model_type       = ModelType.VID2TXT,
            modelname        = self.modelname,
            duration         = duration,
            inference        = iduration,
            input_tokens     = input_tokens,
            output_tokens    = output_tokens,
            load_time_ms     = self.load_time_ms,
            model_size_bytes = self.model_size_bytes,
        )

        return Vid2TxtResponse(
            model   = self.modelname,
            choices = [InstructMessage(role=InstructRole.ASSISTANT, content=outputs[0])],
            usage   = usage,
        )
