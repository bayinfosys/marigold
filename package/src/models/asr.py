"""Automatic speech recognition.

Takes audio input and returns a text transcript with optional
time-aligned segment boundaries.

Uses the HuggingFace AutomaticSpeechRecognition pipeline, which handles
both CTC architectures (wav2vec2, MMS-ASR) and seq2seq architectures
(Whisper, Distil-Whisper) through the same interface.

Audio is resampled to the model's expected sampling rate before inference.
Long audio (over 30 seconds) is chunked automatically by the pipeline.

Compatible models (non-exhaustive):
    openai/whisper-tiny
    openai/whisper-small
    openai/whisper-large-v3
    distil-whisper/distil-large-v3
    facebook/wav2vec2-base-960h
    facebook/mms-300m
"""

import io
import logging
import os
from time import perf_counter as clock

import numpy as np
import torch
from api.models import ASRRequest, ASRResponse, ASRSegment
from models.standard_loader import ModelLoaderResult
from pydub import AudioSegment
from shared.enums import ModelMode, ModelType
from shared.outputs import decode_binary_input
from shared.registry import BaseModelHandler, model_spec
from shared.usage import record_usage

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

_CHUNK_LENGTH_S = 30


def load_asr(modelname: str, cache_dir: str = None, **kwargs) -> ModelLoaderResult:
    """Load an ASR model via the HuggingFace pipeline interface.

    The pipeline abstraction handles CTC and seq2seq architectures without
    requiring separate loader paths. processor is None; the pipeline manages
    its own feature extractor and tokeniser internally.
    """
    from transformers import pipeline as hf_pipeline

    has_cuda = torch.cuda.is_available()
    device = 0 if has_cuda else -1
    dtype = torch.float16 if has_cuda else torch.float32
    local_files_only = os.getenv("HF_HUB_OFFLINE", "true").lower() != "0"

    logger.info("loading '%s' -- cuda=%s dtype=%s", modelname, has_cuda, dtype)

    T0 = clock()

    pipe = hf_pipeline(
        "automatic-speech-recognition",
        model=modelname,
        cache_dir=cache_dir,
        torch_dtype=dtype,
        device=device,
        local_files_only=local_files_only,
    )

    load_time = int((clock() - T0) * 1000)
    logger.info("loaded '%s' pipeline in %0.2fs", modelname, clock() - T0)

    try:
        footprint = pipe.model.get_memory_footprint()
    except Exception:
        footprint = 0

    return ModelLoaderResult(
        processor=None,
        model=pipe,
        model_size_bytes=footprint,
        load_time_ms=load_time,
    )


def _decode_audio(input_str: str, target_sr: int) -> dict:
    """Decode a base64 or s3:// audio input to a pipeline-ready dict.

    Returns {"array": np.ndarray, "sampling_rate": int} where array is
    mono float32 normalised to [-1.0, 1.0] at target_sr.

    decode_binary_input handles the base64/s3:// dispatch. The pydub
    conversion step (format detection, channel collapse, resampling) is
    specific to audio and lives here rather than in shared.outputs.
    """
    raw = decode_binary_input(input_str)

    try:
        audio = AudioSegment.from_file(io.BytesIO(raw))
    except Exception as e:
        raise ValueError(
            "could not decode audio; ensure the input is a supported "
            "format (wav, mp3, flac, ogg, m4a) and ffmpeg is available"
        ) from e

    audio = audio.set_channels(1).set_frame_rate(target_sr)
    samples = np.array(audio.get_array_of_samples(), dtype=np.float32)
    samples = samples / float(1 << (audio.sample_width * 8 - 1))

    return {"array": samples, "sampling_rate": target_sr}


@model_spec(
    model_type=ModelType.ASR,
    mode=ModelMode.GEN,
    output_fields=[],
    loader=load_asr,
    request_model=ASRRequest,
    response_model=ASRResponse,
    route="/gen/asr",
)
class ASRModel(BaseModelHandler):

    def __init__(self, modelname: str):
        super().__init__(modelname)
        self.pipe = self.model
        self.target_sr = getattr(
            getattr(self.pipe, "feature_extractor", None),
            "sampling_rate",
            16000,
        )
        logger.info("'%s' target sample rate: %iHz", modelname, self.target_sr)

    def unload(self) -> None:
        del self.pipe
        super().unload()

    def _run(self, user_id: str, message_id: str, request: ASRRequest) -> ASRResponse:

        T = clock()

        try:
            audio = _decode_audio(request.input, self.target_sr)
        except (ValueError, RuntimeError) as e:
            logger.error("[%s/%s] audio decode failed: %s", user_id, message_id, e)
            raise

        duration_s = len(audio["array"]) / audio["sampling_rate"]
        logger.info(
            "[%s/%s] transcribing %.1fs of audio with '%s'",
            user_id,
            message_id,
            duration_s,
            self.modelname,
        )

        pipe_kwargs = {"return_timestamps": request.return_timestamps}

        if duration_s > _CHUNK_LENGTH_S:
            pipe_kwargs["chunk_length_s"] = _CHUNK_LENGTH_S
            logger.info(
                "[%s/%s] audio exceeds %is, chunking enabled",
                user_id,
                message_id,
                _CHUNK_LENGTH_S,
            )

        if request.language:
            pipe_kwargs["generate_kwargs"] = {"language": request.language}

        T1 = clock()
        result = self.pipe(audio, **pipe_kwargs)
        iduration = clock() - T1

        text = result.get("text", "").strip()

        segments = None
        if request.return_timestamps and "chunks" in result:
            segments = []
            for i, chunk in enumerate(result["chunks"]):
                ts = chunk.get("timestamp") or (0.0, 0.0)
                segments.append(
                    ASRSegment(
                        id=i,
                        start=ts[0] if ts[0] is not None else 0.0,
                        end=ts[1] if ts[1] is not None else 0.0,
                        text=chunk.get("text", "").strip(),
                    )
                )

        duration = clock() - T

        logger.info(
            "[%s/%s] '%s' produced %i chars in %0.2fs (inference %0.2fs)",
            user_id,
            message_id,
            self.modelname,
            len(text),
            duration,
            iduration,
        )

        usage = record_usage(
            user_id=user_id,
            model_type=ModelType.ASR,
            modelname=self.modelname,
            duration=duration,
            inference=iduration,
            output_tokens=len(text.split()),
            load_time_ms=self.load_time_ms,
            model_size_bytes=self.model_size_bytes,
        )

        return ASRResponse(
            model=self.modelname,
            language=request.language or "und",
            text=text,
            segments=segments,
            usage=usage,
        )
