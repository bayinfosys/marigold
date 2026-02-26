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
from api.models import ModelType, TTSRequest, TTSResponse
from models import BaseModelHandler
from models.cache_model import load_tts
from pydub import AudioSegment
from shared import record_usage, write_binary_output

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

LAME_PATH = os.getenv("LAME_PATH", "/var/task/lame")
AudioSegment.converter = LAME_PATH

OUTPUT_BUCKET = os.environ["OUTPUT_BUCKET"]


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


class TTSModel(BaseModelHandler):

    def __init__(self, modelname: str):
        super().__init__(modelname)
        self.lang_code = os.getenv("MODEL_LANGCODE", "")
        _T = clock()
        self.tokenizer, self.model = load_tts(modelname)
        logger.info("'%s' loaded in %0.2fs", modelname, clock() - _T)

    def process(self, user_id: str, message_id: str, request: dict) -> TTSResponse:
        req = TTSRequest.model_validate(request)
        return self._run(user_id, message_id, req)

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
        inputs = self.tokenizer(request.text, return_tensors="pt")

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
        audio_mimetype = "audio/mpeg"
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

        output_reference = write_binary_output(
            message_id=message_id,
            model_type=ModelType.TTS,
            field_name="audio",
            data=mp3,
            mimetype=audio_mimetype,
            bucket=OUTPUT_BUCKET,
        )

        usage = record_usage(
            user_id,
            ModelType.TTS,
            self.modelname,
            duration,
            iduration,
            input_tokens=inputs.input_ids.nelement(),
        )

        return TTSResponse(
            model=self.modelname,
            usage=usage,
            language_code=request.language_code,
            outputs={"audio": output_reference},
        )
