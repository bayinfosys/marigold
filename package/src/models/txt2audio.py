"""Text-to-audio generation: music and sound effects.

Takes a text prompt and returns a generated audio clip written to S3.

Two model families are supported:

  facebook/musicgen-small   (300M)  -- music, 32kHz mono, up to 30s
  facebook/musicgen-medium  (1.5B)  -- music, 32kHz mono, up to 30s
  cvssp/audioldm2           (---)   -- music and sound effects, 16kHz, variable length

MusicGen generates audio autoregressively at 50 tokens/second. The
duration_seconds request field is converted to max_new_tokens. AudioLDM2
is a latent diffusion model; duration_seconds maps directly to
audio_length_in_s and num_inference_steps controls quality vs. speed
(default 200, reduce to ~50 for faster CPU inference at lower quality).

Both paths share the same WAV -> MP3 conversion utilities from tts.py.

Memory guidance:
  musicgen-small    ~2.5 GB
  musicgen-medium   ~6 GB
  audioldm2         ~9 GB

Compatible models:
    facebook/musicgen-small
    facebook/musicgen-medium
    cvssp/audioldm2
    cvssp/audioldm2-music
"""

import io
import logging
import os
import wave
from time import perf_counter as clock

import numpy as np
import torch
from pydub import AudioSegment

from shared.enums import ModelMode, ModelType, OutputMimeType
from shared.registry import BaseModelHandler, OutputField, model_spec
from shared.usage import record_usage
from models.standard_loader import ModelLoaderResult
from api.models import Txt2AudioRequest, Txt2AudioResponse

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

LAME_PATH = os.getenv("LAME_PATH", "/var/task/lame")
AudioSegment.converter = LAME_PATH

# MusicGen generates 50 audio tokens per second of output.
_MUSICGEN_TOKENS_PER_SECOND = 50

# AudioLDM2 default inference steps. High quality but slow on CPU.
# Override per-model via extra_env: NUM_INFERENCE_STEPS in models.yaml.
_AUDIOLDM2_DEFAULT_STEPS = 200


def _numpy_to_wave(arr: np.ndarray, sample_rate: int) -> bytes:
    """Convert a float32 numpy waveform to WAV bytes."""
    scaled = np.int16(arr * 32768)
    with io.BytesIO() as f:
        with wave.open(f, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(scaled.tobytes())
        return f.getvalue()


def _wave_to_mp3(wav_bytes: bytes) -> bytes:
    """Convert WAV bytes to MP3 at 192 kbps via pydub/lame."""
    audio = AudioSegment.from_wav(io.BytesIO(wav_bytes))
    buf = io.BytesIO()
    audio.export(buf, format="mp3", bitrate="192k")
    return buf.getvalue()


def load_txt2audio(modelname: str, cache_dir: str = None, **kwargs) -> ModelLoaderResult:
    """Text-to-audio / music generation.

    Supports two model families:
      - facebook/musicgen-*: loaded via MusicgenForConditionalGeneration +
        AutoProcessor. Output is a (batch, channels, samples) tensor at 32kHz.
      - cvssp/audioldm2*: loaded via diffusers AudioLDM2Pipeline. Output is a
        (samples,) numpy array at 16kHz.

    Returns a ModelLoaderResult with processor=None for the AudioLDM2 path
    (the pipeline carries its own processor internally).
    """
    T0 = clock()

    if modelname.startswith("facebook/musicgen"):
        from transformers import AutoProcessor as P
        from transformers import MusicgenForConditionalGeneration as M

        processor = P.from_pretrained(
            modelname,
            cache_dir=cache_dir,
            local_files_only=kwargs.get("local_files_only", True),
        )
        model = M.from_pretrained(
            modelname,
            cache_dir=cache_dir,
            local_files_only=kwargs.get("local_files_only", True),
        )
        model.eval()
        logger.info("loaded '%s' MusicGen in %0.2fs", modelname, clock() - T0)
        return ModelLoaderResult(processor=processor, model=model)

    if modelname.startswith("cvssp/audioldm2"):
        from diffusers import AudioLDM2Pipeline

        pipe = AudioLDM2Pipeline.from_pretrained(modelname, cache_dir=cache_dir)
        logger.info("loaded '%s' AudioLDM2 pipeline in %0.2fs", modelname, clock() - T0)
        return ModelLoaderResult(processor=None, model=pipe)

    raise ValueError(
        "load_txt2audio: unsupported model '%s'; "
        "expected facebook/musicgen-* or cvssp/audioldm2*" % modelname
    )


@model_spec(
    model_type=ModelType.TXT2AUDIO,
    mode=ModelMode.GEN,
    output_fields=[OutputField(name="audio", mimetype=OutputMimeType.AUDIO_MP3)],
    loader=load_txt2audio,
    request_model=Txt2AudioRequest,
    response_model=Txt2AudioResponse,
    route="/gen/txt2audio",
)
class Txt2AudioModel(BaseModelHandler):

    def __init__(self, modelname: str):
        super().__init__(modelname)
        self._is_musicgen = modelname.startswith("facebook/musicgen")
        self._default_steps = int(
            os.getenv("NUM_INFERENCE_STEPS", str(_AUDIOLDM2_DEFAULT_STEPS))
        )

    def _run(
        self, user_id: str, message_id: str, request: Txt2AudioRequest
    ) -> Txt2AudioResponse:
        if self._is_musicgen:
            return self._run_musicgen(user_id, message_id, request)
        return self._run_audioldm2(user_id, message_id, request)

    def _run_musicgen(
        self, user_id: str, message_id: str, request: Txt2AudioRequest
    ) -> Txt2AudioResponse:
        max_new_tokens = int(request.duration_seconds * _MUSICGEN_TOKENS_PER_SECOND)

        logger.info(
            "[%s/%s] MusicGen '%s' prompt='%s' duration=%.1fs tokens=%i",
            user_id,
            message_id,
            self.modelname,
            request.prompt[:80],
            request.duration_seconds,
            max_new_tokens,
        )

        T = clock()

        inputs = self.processor(
            text=[request.prompt],
            padding=True,
            return_tensors="pt",
        )

        if request.seed is not None:
            torch.manual_seed(request.seed)

        T1 = clock()
        with torch.no_grad():
            audio_values = self.model.generate(
                **inputs,
                do_sample=True,
                guidance_scale=request.guidance_scale,
                max_new_tokens=max_new_tokens,
            )
        iduration = clock() - T1

        # audio_values: (batch=1, channels=1, samples)
        arr = audio_values[0, 0].cpu().numpy().astype(np.float32)
        sample_rate = self.model.config.audio_encoder.sampling_rate

        wav = _numpy_to_wave(arr, sample_rate)
        mp3 = _wave_to_mp3(wav)
        duration = clock() - T

        logger.info(
            "[%s/%s] '%s' generated %.1fs audio (%ib mp3) in %0.2fs (inference %0.2fs)",
            user_id,
            message_id,
            self.modelname,
            len(arr) / sample_rate,
            len(mp3),
            duration,
            iduration,
        )

        output_reference = self.write_output("audio", mp3, message_id)

        usage = record_usage(
            user_id=user_id,
            model_type=ModelType.TXT2AUDIO,
            modelname=self.modelname,
            duration=duration,
            inference=iduration,
            input_tokens=inputs.input_ids.nelement(),
        )

        return Txt2AudioResponse(
            model=self.modelname,
            usage=usage,
            outputs={"audio": output_reference},
        )

    def _run_audioldm2(
        self, user_id: str, message_id: str, request: Txt2AudioRequest
    ) -> Txt2AudioResponse:
        num_steps = request.num_inference_steps or self._default_steps

        logger.info(
            "[%s/%s] AudioLDM2 '%s' prompt='%s' duration=%.1fs steps=%i",
            user_id,
            message_id,
            self.modelname,
            request.prompt[:80],
            request.duration_seconds,
            num_steps,
        )

        T = clock()

        pipe_kwargs = dict(
            prompt=request.prompt,
            audio_length_in_s=request.duration_seconds,
            num_inference_steps=num_steps,
            guidance_scale=request.guidance_scale,
            num_waveforms_per_prompt=1,
        )
        if request.negative_prompt:
            pipe_kwargs["negative_prompt"] = request.negative_prompt
        if request.seed is not None:
            pipe_kwargs["generator"] = torch.Generator().manual_seed(request.seed)

        T1 = clock()
        result = self.model(**pipe_kwargs)
        iduration = clock() - T1

        # result.audios: (batch=1, samples) at 16kHz
        arr = result.audios[0].astype(np.float32)
        sample_rate = 16000

        wav = _numpy_to_wave(arr, sample_rate)
        mp3 = _wave_to_mp3(wav)
        duration = clock() - T

        logger.info(
            "[%s/%s] '%s' generated %.1fs audio (%ib mp3) in %0.2fs (inference %0.2fs)",
            user_id,
            message_id,
            self.modelname,
            len(arr) / sample_rate,
            len(mp3),
            duration,
            iduration,
        )

        output_reference = self.write_output("audio", mp3, message_id)

        usage = record_usage(
            user_id=user_id,
            model_type=ModelType.TXT2AUDIO,
            modelname=self.modelname,
            duration=duration,
            inference=iduration,
        )

        return Txt2AudioResponse(
            model=self.modelname,
            usage=usage,
            outputs={"audio": output_reference},
        )
