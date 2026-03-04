"""Text-to-speech synthesis using Facebook MMS models.

Language coverage: https://dl.fbaipublicfiles.com/mms/misc/language_coverage_mms.html

Each TTS model is language-specific. The language code is part of the model
name (e.g. facebook/mms-tts-eng) and is also stored in MODEL_LANGCODE by
Terraform. The request must include a language_code field; the handler logs a
warning if it does not match the loaded model's language but does not reject
the request, since the model itself enforces compatibility.

Compatible models:
    facebook/mms-tts-eng
    facebook/mms-tts-cym
    facebook/mms-tts-deu
    facebook/mms-tts-fra
    facebook/mms-tts-spa
    facebook/mms-tts-fin
    facebook/mms-tts-nld
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
from models.standard_loader import ModelLoaderResult, standard_loader
from api.models import TTSRequest, TTSResponse

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

LAME_PATH = os.getenv("LAME_PATH", "/var/task/lame")
AudioSegment.converter = LAME_PATH


def load_tts(modelname: str, cache_dir: str = None, **kwargs) -> ModelLoaderResult:
    """Text-to-speech models.

    The parler-tts family uses a seq2seq architecture and bypasses
    standard_loader. processor is None for that path; the model is called
    directly with text inputs at inference time.
    """
    from transformers import AutoModelForTextToWaveform as M
    from transformers import AutoTokenizer as T

    if modelname.startswith("parler-tts/"):
        from transformers import AutoModelForSeq2SeqLM as ParlerM

        parler_model = ParlerM.from_pretrained(modelname, cache_dir=cache_dir)
        return ModelLoaderResult(processor=None, model=parler_model)

    return standard_loader(T, M, modelname, cache_dir=cache_dir, **kwargs)


def _numpy_to_wave(arr: np.ndarray, sample_rate: int) -> bytes:
    """Convert a float numpy waveform array to WAV bytes."""
    scaled = np.int16(arr * 32768)
    logger.debug(
        "wave: shape=%s dtype=%s range=[%d, %d]",
        str(scaled.shape),
        str(scaled.dtype),
        scaled.min(),
        scaled.max(),
    )
    with io.BytesIO() as f:
        with wave.open(f, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(scaled.tobytes())
        return f.getvalue()


def _wave_to_mp3(wav_bytes: bytes) -> bytes:
    """Convert WAV bytes to MP3 bytes at 192 kbps using pydub/lame."""
    audio = AudioSegment.from_wav(io.BytesIO(wav_bytes))
    buf = io.BytesIO()
    audio.export(buf, format="mp3", bitrate="192k")
    return buf.getvalue()


@model_spec(
    model_type=ModelType.TTS,
    mode=ModelMode.GEN,
    output_fields=[OutputField(name="audio", mimetype=OutputMimeType.AUDIO_MP3)],
    loader=load_tts,
    request_model=TTSRequest,
    response_model=TTSResponse,
    route="/gen/tts",
)
class TTSModel(BaseModelHandler):

    def __init__(self, modelname: str):
        super().__init__(modelname)
        self.lang_code = os.getenv("MODEL_LANGCODE", "")

    def _run(self, user_id: str, message_id: str, request: TTSRequest) -> TTSResponse:
        if self.lang_code and request.language_code != self.lang_code:
            logger.warning(
                "[%s/%s] language_code mismatch: request=%s model=%s",
                user_id,
                message_id,
                request.language_code,
                self.lang_code,
            )

        logger.info(
            "[%s/%s] synthesising %i chars in '%s'",
            user_id,
            message_id,
            len(request.text),
            request.language_code,
        )

        T = clock()
        inputs = self.processor(request.text, return_tensors="pt")

        T1 = clock()
        with torch.no_grad():
            waveform = self.model(**inputs).waveform
        iduration = clock() - T1

        logger.debug(
            "[%s/%s] waveform shape=%s range=[%0.4f, %0.4f]",
            user_id,
            message_id,
            str(waveform.shape),
            waveform.min().item(),
            waveform.max().item(),
        )

        wav = _numpy_to_wave(
            waveform.squeeze().numpy(), self.model.config.sampling_rate
        )
        mp3 = _wave_to_mp3(wav)
        duration = clock() - T

        logger.info(
            "[%s/%s] '%s' audio %ib in %0.2fs (inference %0.2fs)",
            user_id,
            message_id,
            self.modelname,
            len(mp3),
            duration,
            iduration,
        )

        output_reference = self.write_output("audio", mp3, message_id)

        usage = record_usage(
            user_id=user_id,
            model_type=ModelType.TTS,
            modelname=self.modelname,
            duration=duration,
            inference=iduration,
            input_tokens=inputs.input_ids.nelement(),
        )

        return TTSResponse(
            model=self.modelname,
            usage=usage,
            language_code=request.language_code,
            outputs={"audio": output_reference},
        )
