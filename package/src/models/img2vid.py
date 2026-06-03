"""Image-to-video generation.

Takes one or more image keyframes and returns a generated video written to S3.

Keyframe handling by model capability:

  Single conditioning image (SVD, CogVideoX-I2V, Wan2.1-I2V):
    Uses keyframes[0].image. Additional keyframes are logged and ignored.

  Start/end frame conditioning (CogVideoX-Fun, Wan2.1-Fun):
    Uses keyframes[0] as the first frame and keyframes[-1] as the last.
    The pipeline interpolates the intervening frames. Intermediate
    keyframes between the two endpoints are ignored for these models.

  Multi-reference conditioning (DynamiCrafter):
    All keyframes are passed to the pipeline. Timestamps are converted
    to frame indices using the requested fps.

The appropriate path is selected at runtime via the KEYFRAME_MODE env var
set per-model in models.yaml extra_env:

    KEYFRAME_MODE=single        (default)
    KEYFRAME_MODE=start_end
    KEYFRAME_MODE=multi

Compatible models (non-exhaustive):
    stabilityai/stable-video-diffusion-img2vid-xt   KEYFRAME_MODE=single
    THUDM/CogVideoX-5b-I2V                          KEYFRAME_MODE=single
    Wan-AI/Wan2.1-I2V-14B                           KEYFRAME_MODE=single
    alibaba-pai/CogVideoX-Fun-V1.1-5b-InP           KEYFRAME_MODE=start_end
    Wan-AI/Wan2.1-Fun-14B-InP                       KEYFRAME_MODE=start_end
    Doubiiu/DynamiCrafter                           KEYFRAME_MODE=multi
"""

import logging
import os
from time import perf_counter as clock

import torch
from PIL import Image

from api.models import Img2VidRequest, Img2VidResponse, VideoKeyframe
from models.standard_loader import ModelLoaderResult
from shared.enums import ModelMode, ModelType, OutputMimeType
from shared.outputs import decode_image, frames_to_mp4_bytes
from shared.registry import BaseModelHandler, OutputField, model_spec
from shared.usage import record_usage

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

_DEFAULT_NUM_STEPS    = 25
_VALID_KEYFRAME_MODES = {"single", "start_end", "multi"}


def load_img2vid(modelname: str, cache_dir: str = None, **kwargs) -> ModelLoaderResult:
    """Image-to-video via diffusers DiffusionPipeline.

    Identical load path to txt2vid. The pipeline class is determined by
    the model config at load time, not by this loader.
    """
    from diffusers import DiffusionPipeline

    has_cuda  = torch.cuda.is_available()
    gpu_count = torch.cuda.device_count() if has_cuda else 0
    dtype     = torch.float16 if has_cuda else torch.float32
    local_files_only = os.getenv("HF_HUB_OFFLINE", "true").lower() != "0"

    logger.info(
        "loading '%s' -- cuda=%s gpus=%d dtype=%s",
        modelname, has_cuda, gpu_count, dtype,
    )

    T0 = clock()

    load_kwargs = dict(
        cache_dir        = cache_dir,
        torch_dtype      = dtype,
        local_files_only = local_files_only,
    )

    if gpu_count > 1:
        load_kwargs["device_map"] = "balanced"
        pipe = DiffusionPipeline.from_pretrained(modelname, **load_kwargs)
    else:
        target = "cuda" if has_cuda else "cpu"
        pipe = DiffusionPipeline.from_pretrained(modelname, **load_kwargs).to(target)

    load_time = int((clock() - T0) * 1000)
    logger.info("loaded '%s' in %0.2fs", modelname, clock() - T0)

    try:
        footprint = pipe.transformer.get_memory_footprint()
    except AttributeError:
        try:
            footprint = pipe.unet.get_memory_footprint()
        except AttributeError:
            footprint = 0

    return ModelLoaderResult(
        processor        = None,
        model            = pipe,
        model_size_bytes = footprint,
        load_time_ms     = load_time,
    )


def _decode_keyframe(kf: VideoKeyframe) -> Image.Image:
    """Decode a VideoKeyframe image to a PIL Image."""
    try:
        return decode_image(kf.image)
    except Exception as e:
        raise ValueError("could not decode keyframe image") from e


def _resolve_timestamps(keyframes: list, num_frames: int, fps: int) -> list:
    """Return a list of (PIL.Image, frame_index) pairs.

    When all timestamps are None, keyframes are distributed uniformly
    across the frame range. When timestamps are provided, they are
    converted to frame indices by multiplying by fps and rounding.

    Frame indices are clamped to [0, num_frames - 1].
    """
    n     = len(keyframes)
    pairs = []

    for i, kf in enumerate(keyframes):
        image = _decode_keyframe(kf)
        if kf.timestamp is not None:
            idx = round(kf.timestamp * fps)
        else:
            idx = round(i * (num_frames - 1) / max(n - 1, 1))
        idx = max(0, min(idx, num_frames - 1))
        pairs.append((image, idx))

    return pairs


@model_spec(
    model_type     = ModelType.IMG2VID,
    mode           = ModelMode.GEN,
    output_fields  = [OutputField(name="video", mimetype=OutputMimeType.VIDEO_MP4)],
    loader         = load_img2vid,
    request_model  = Img2VidRequest,
    response_model = Img2VidResponse,
    route          = "/gen/img2vid",
)
class Img2VidModel(BaseModelHandler):

    def __init__(self, modelname: str):
        super().__init__(modelname)
        self.pipe          = self.model
        self.num_steps     = int(os.getenv("NUM_STEPS", str(_DEFAULT_NUM_STEPS)))
        self.keyframe_mode = os.getenv("KEYFRAME_MODE", "single")

        if self.keyframe_mode not in _VALID_KEYFRAME_MODES:
            logger.warning(
                "'%s' has unrecognised KEYFRAME_MODE='%s', falling back to 'single'",
                modelname, self.keyframe_mode,
            )
            self.keyframe_mode = "single"

        logger.info("'%s' keyframe_mode=%s", modelname, self.keyframe_mode)

    def _run(
        self, user_id: str, message_id: str, request: Img2VidRequest
    ) -> Img2VidResponse:

        num_steps = request.num_inference_steps if request.num_inference_steps is not None \
                    else self.num_steps

        logger.info(
            "[%s/%s] img2vid: keyframes=%i mode=%s frames=%i fps=%i steps=%i",
            user_id, message_id,
            len(request.keyframes),
            self.keyframe_mode,
            request.num_frames,
            request.fps,
            num_steps,
        )

        if self.keyframe_mode != "single" and len(request.keyframes) > 1:
            logger.info(
                "[%s/%s] keyframe timestamps: %s",
                user_id, message_id,
                [kf.timestamp for kf in request.keyframes],
            )

        T = clock()

        pipe_kwargs = dict(
            num_frames          = request.num_frames,
            num_inference_steps = num_steps,
            guidance_scale      = request.guidance_scale,
            output_type         = "pil",
        )

        if request.prompt:
            pipe_kwargs["prompt"] = request.prompt
        if request.negative_prompt:
            pipe_kwargs["negative_prompt"] = request.negative_prompt
        if request.seed is not None:
            pipe_kwargs["generator"] = torch.Generator().manual_seed(request.seed)

        if self.keyframe_mode == "single":
            if len(request.keyframes) > 1:
                logger.warning(
                    "[%s/%s] %i keyframes provided but KEYFRAME_MODE=single; "
                    "using keyframes[0] only",
                    user_id, message_id, len(request.keyframes),
                )
            pipe_kwargs["image"] = _decode_keyframe(request.keyframes[0])

        elif self.keyframe_mode == "start_end":
            if len(request.keyframes) < 2:
                raise ValueError(
                    "KEYFRAME_MODE=start_end requires at least 2 keyframes; "
                    "got %i" % len(request.keyframes)
                )
            if len(request.keyframes) > 2:
                logger.warning(
                    "[%s/%s] %i keyframes provided but KEYFRAME_MODE=start_end "
                    "uses only first and last",
                    user_id, message_id, len(request.keyframes),
                )
            pipe_kwargs["image"]      = _decode_keyframe(request.keyframes[0])
            pipe_kwargs["last_image"] = _decode_keyframe(request.keyframes[-1])

        elif self.keyframe_mode == "multi":
            resolved   = _resolve_timestamps(
                request.keyframes, request.num_frames, request.fps
            )
            images     = [img for img, _ in resolved]
            frame_idxs = [idx for _, idx in resolved]
            pipe_kwargs["images"]             = images
            pipe_kwargs["conditioning_frames"] = frame_idxs
            logger.info(
                "[%s/%s] multi keyframes at frame indices %s",
                user_id, message_id, frame_idxs,
            )

        result    = self.pipe(**pipe_kwargs)
        iduration = clock() - T

        frames = result.frames[0]

        logger.info(
            "[%s/%s] '%s' generated %i frames in %0.2fs (inference %0.2fs)",
            user_id, message_id, self.modelname,
            len(frames), clock() - T, iduration,
        )

        video_bytes = frames_to_mp4_bytes(frames, request.fps)
        duration    = clock() - T

        output_reference = self.write_output("video", video_bytes, message_id)

        usage = record_usage(
            user_id          = user_id,
            model_type       = ModelType.IMG2VID,
            modelname        = self.modelname,
            duration         = duration,
            inference        = iduration,
            load_time_ms     = self.load_time_ms,
            model_size_bytes = self.model_size_bytes,
        )

        return Img2VidResponse(
            model      = self.modelname,
            usage      = usage,
            num_frames = len(frames),
            fps        = request.fps,
            outputs    = {"video": output_reference},
        )
