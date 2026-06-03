"""Video-to-video transformation.

Takes a source video and returns a transformed video written to S3.

The source video is decoded to frames, passed to a video diffusion pipeline
as conditioning, and the output frames are encoded to MP4. The strength
parameter controls how much the pipeline deviates from the source.

Uses diffusers DiffusionPipeline, which dispatches to the correct pipeline
class for each model (VideoToVideoSDPipeline, CogVideoXVideoToVideoPipeline,
etc.).

Frame count: the output frame count is determined by the pipeline from the
number of conditioning frames passed in. MAX_INPUT_FRAMES (env var, default
24) caps how many source frames are extracted before passing to the pipeline.
Increase this for models with longer context windows; decrease it to reduce
VRAM usage.

Compatible models (non-exhaustive):
    cerspense/zeroscope_v2_XL
    cerspense/zeroscope_v2_576w
    Wan-AI/Wan2.1-Fun-14B-InP       (also handles vid2vid with strength)
    THUDM/CogVideoX-5b              (via CogVideoXVideoToVideoPipeline)
"""

import logging
import os
from time import perf_counter as clock

import torch

from api.models import Vid2VidRequest, Vid2VidResponse
from models.standard_loader import ModelLoaderResult
from shared.enums import ModelMode, ModelType, OutputMimeType
from shared.outputs import decode_video_frames, frames_to_mp4_bytes
from shared.registry import BaseModelHandler, OutputField, model_spec
from shared.usage import record_usage

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

_DEFAULT_NUM_STEPS     = 50
_DEFAULT_MAX_IN_FRAMES = 24


def load_vid2vid(modelname: str, cache_dir: str = None, **kwargs) -> ModelLoaderResult:
    """Video-to-video via diffusers DiffusionPipeline.

    Identical load path to txt2vid and img2vid. The pipeline class is
    determined by the model config at load time.
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


@model_spec(
    model_type     = ModelType.VID2VID,
    mode           = ModelMode.GEN,
    output_fields  = [OutputField(name="video", mimetype=OutputMimeType.VIDEO_MP4)],
    loader         = load_vid2vid,
    request_model  = Vid2VidRequest,
    response_model = Vid2VidResponse,
    route          = "/gen/vid2vid",
)
class Vid2VidModel(BaseModelHandler):

    def __init__(self, modelname: str):
        super().__init__(modelname)
        self.pipe          = self.model
        self.num_steps     = int(os.getenv("NUM_STEPS",        str(_DEFAULT_NUM_STEPS)))
        self.max_in_frames = int(os.getenv("MAX_INPUT_FRAMES", str(_DEFAULT_MAX_IN_FRAMES)))

        logger.info(
            "'%s' max_input_frames=%i default_steps=%i",
            modelname, self.max_in_frames, self.num_steps,
        )

    def _run(
        self, user_id: str, message_id: str, request: Vid2VidRequest
    ) -> Vid2VidResponse:

        T = clock()

        try:
            frames = decode_video_frames(request.input, self.max_in_frames)
        except (ValueError, RuntimeError) as e:
            logger.error("[%s/%s] video decode failed: %s", user_id, message_id, e)
            raise

        num_steps = request.num_inference_steps if request.num_inference_steps is not None \
                    else self.num_steps

        logger.info(
            "[%s/%s] vid2vid: source_frames=%i strength=%.2f steps=%i fps=%i",
            user_id, message_id,
            len(frames),
            request.strength,
            num_steps,
            request.fps,
        )

        pipe_kwargs = dict(
            video               = frames,
            strength            = request.strength,
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

        result    = self.pipe(**pipe_kwargs)
        iduration = clock() - T

        output_frames = result.frames[0]

        logger.info(
            "[%s/%s] '%s' generated %i frames in %0.2fs (inference %0.2fs)",
            user_id, message_id, self.modelname,
            len(output_frames), clock() - T, iduration,
        )

        video_bytes = frames_to_mp4_bytes(output_frames, request.fps)
        duration    = clock() - T

        logger.info(
            "[%s/%s] encoded %i frames to MP4 (%ib) in %0.2fs total",
            user_id, message_id,
            len(output_frames), len(video_bytes), duration,
        )

        output_reference = self.write_output("video", video_bytes, message_id)

        usage = record_usage(
            user_id          = user_id,
            model_type       = ModelType.VID2VID,
            modelname        = self.modelname,
            duration         = duration,
            inference        = iduration,
            load_time_ms     = self.load_time_ms,
            model_size_bytes = self.model_size_bytes,
        )

        return Vid2VidResponse(
            model      = self.modelname,
            usage      = usage,
            num_frames = len(output_frames),
            fps        = request.fps,
            outputs    = {"video": output_reference},
        )
