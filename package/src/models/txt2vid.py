"""Text-to-video generation.

Takes a text prompt and returns a video written to S3.

Uses diffusers DiffusionPipeline, which auto-dispatches to the correct
pipeline class for each model family (CogVideoXPipeline, WanPipeline, etc.).
The pipeline is stored as self.pipe, consistent with txt2img.

Video frames are exported to MP4 via imageio-ffmpeg. The output key 'video'
in the response outputs dict contains the S3 reference.

Video generation is significantly slower than image generation. Expect
several minutes per request on a single GPU for 2-5B parameter models.
Run this type on GPU instances only; CPU inference is not practical.

Note on num_frames: many video DiT models require num_frames = 4k + 1
(49, 81, 97, etc.). The request default of 49 is valid for all supported
model families. Passing an invalid value raises an error from the pipeline
before inference begins.

Compatible models (non-exhaustive):
    THUDM/CogVideoX-2b
    THUDM/CogVideoX-5b
    Wan-AI/Wan2.1-T2V-1.3B
    Wan-AI/Wan2.1-T2V-14B
"""

import logging
import os
from time import perf_counter as clock

import torch

from api.models import Txt2VidRequest, Txt2VidResponse
from models.standard_loader import ModelLoaderResult, load_diffusion_pipeline
from shared.enums import ModelMode, ModelType, OutputMimeType
from shared.outputs import frames_to_mp4_bytes
from shared.registry import BaseModelHandler, OutputField, model_spec
from shared.usage import build_usage

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

_DEFAULT_NUM_STEPS = 50


def load_txt2vid(modelname: str, cache_dir: str = None, **kwargs) -> ModelLoaderResult:
    """Text-to-video via diffusers DiffusionPipeline."""
    return load_diffusion_pipeline(modelname, cache_dir)


@model_spec(
    model_type     = ModelType.TXT2VID,
    mode           = ModelMode.GEN,
    output_fields  = [OutputField(name="video", mimetype=OutputMimeType.VIDEO_MP4)],
    loader         = load_txt2vid,
    request_model  = Txt2VidRequest,
    response_model = Txt2VidResponse,
    route          = "/gen/txt2vid",
)
class Txt2VidModel(BaseModelHandler):

    def __init__(self, modelname: str):
        super().__init__(modelname)
        self.pipe      = self.model
        self.num_steps = int(os.getenv("NUM_STEPS", str(_DEFAULT_NUM_STEPS)))

    def unload(self) -> None:
        del self.pipe
        super().unload()

    def _run(
        self, user_id: str, message_id: str, request: Txt2VidRequest
    ) -> Txt2VidResponse:

        num_steps = request.num_inference_steps if request.num_inference_steps is not None \
                    else self.num_steps

        logger.info(
            "[%s/%s] generating video: prompt='%s' frames=%i fps=%i steps=%i",
            user_id, message_id,
            request.prompt[:80],
            request.num_frames,
            request.fps,
            num_steps,
        )

        T = clock()

        pipe_kwargs = dict(
            prompt              = request.prompt,
            num_frames          = request.num_frames,
            num_inference_steps = num_steps,
            guidance_scale      = request.guidance_scale,
            output_type         = "pil",
        )

        if request.negative_prompt:
            pipe_kwargs["negative_prompt"] = request.negative_prompt
        if request.width:
            pipe_kwargs["width"] = request.width
        if request.height:
            pipe_kwargs["height"] = request.height
        if request.seed is not None:
            pipe_kwargs["generator"] = torch.Generator().manual_seed(request.seed)

        result    = self.pipe(**pipe_kwargs)
        iduration = clock() - T

        # result.frames is List[List[PIL.Image]] -- batch x frames
        # take the first (and typically only) video in the batch
        frames = result.frames[0]

        logger.info(
            "[%s/%s] '%s' generated %i frames in %0.2fs (inference %0.2fs)",
            user_id, message_id, self.modelname,
            len(frames), clock() - T, iduration,
        )

        video_bytes = frames_to_mp4_bytes(frames, request.fps)
        duration    = clock() - T

        logger.info(
            "[%s/%s] encoded %i frames to MP4 (%ib) in %0.2fs total",
            user_id, message_id, len(frames), len(video_bytes), duration,
        )

        output_reference = self.write_output("video", video_bytes, message_id)

        usage = build_usage(
            user_id          = user_id,
            model_type       = ModelType.TXT2VID,
            modelname        = self.modelname,
            duration         = duration,
            inference        = iduration,
            load_time_ms     = self.load_time_ms,
            model_size_bytes = self.model_size_bytes,
        )

        return Txt2VidResponse(
            model      = self.modelname,
            usage      = usage,
            num_frames = len(frames),
            fps        = request.fps,
            outputs    = {"video": output_reference},
        )
