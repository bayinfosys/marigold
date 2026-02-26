"""txt2speech using facebook mms models

https://dl.fbaipublicfiles.com/mms/misc/language_coverage_mms.html

input must include a language code which must match the model language code in the environment

TODO: creating a mapping from MODELNAME to language code for validation
"""
import os
import io
import logging
import numpy as np

from time import perf_counter as clock

import torch

import wave
from pydub import AudioSegment  # mp3 conversion

LAME_PATH = os.getenv("LAME_PATH", "/var/task/lame")
AudioSegment.converter = LAME_PATH

from shared import (
    get_userid_from_event,
    lambda_event_to_data,
    mk_resp,
    update_metrics,
    get_memory_usage,
    write_binary_output,
)
from api.models import (
    ModelType,
    ModelUsageStats,
    OutputReference,
    TTSRequest,
    TTSResponse,
)

from models.cache_model import load_tts, ModelNotFoundError

logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL") or "INFO")


MODELNAME = os.environ["MODELNAME"]
OUTPUT_BUCKET = os.environ["OUTPUT_BUCKET"]

T = clock()

try:
    tokenizer, model = load_tts(MODELNAME)
except ModelNotFoundError as e:
    logger.error("unable to load '%s' [%s]", str(MODELNAME), str(e))
    tokenizer, model = None, None

logger.info("'%s' loaded in '%0.2fs", MODELNAME, (clock() - T))


def wave_to_mp3(wav):
    """Convert WAV bytes to MP3 bytes using pydub."""
    audio = AudioSegment.from_wav(io.BytesIO(wav))
    mp3_io = io.BytesIO()
    audio.export(mp3_io, format="mp3", bitrate="192k")
    return mp3_io.getvalue()


def numpy_to_wave(arr, sample_rate: int):
    """convert a numpy array to wave bytes"""
    sc = np.int16(arr * 32768)

    logger.info(
        "scaled '%s.%s' [%0.3f->%0.3f] to '%s.%s' [%d->%d]",
        str(arr.dtype), str(arr.shape), arr.min(), arr.max(),
        str(sc.dtype), str(sc.shape), sc.min(), sc.max(),
    )

    with io.BytesIO() as f:
        with wave.open(f, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(sc.tobytes())
        return f.getvalue()


def lambda_handler(event, context):
    logger.info("event: '%s'", str(event))

    try:
        user_id = get_userid_from_event(event)
    except Exception as e:
        logger.error("failed to get user_id from event '%s' [%s]", str(event), str(e))
        return mk_resp(400, {"status": "error", "message": "missing userid"})

    try:
        data, mimetype = lambda_event_to_data(event, data_key="body")
    except KeyError as e:
        return mk_resp(400, {"status": "error", "message": "missing key: '%s'" % str(e)})

    try:
        request = TTSRequest(**data)
    except Exception as e:
        logger.error("unable to validate TTSRequest as '%s'", str(data))
        return mk_resp(400, {"status": "error", "message": "input validation error [%s]" % str(e)})

    # NB: message_id is passed in the event by the polling lambda
    message_id = event.get("message_id")
    if not message_id:
        return mk_resp(400, {"status": "error", "message": "message_id required"})

    text = request.text
    lang_code = request.language_code

    logger.info("tts over: '%s' [%i]", str(text), len(text))

    T = clock()
    inputs = tokenizer(text, return_tensors="pt")

    T1 = clock()
    with torch.no_grad():
        output = model(**inputs).waveform
    iduration = clock() - T1

    logger.info(
        "completed '%s.%s' [%0.4f->%0.4f] in %0.2fs",
        str(output.shape), str(output.dtype),
        output.min(), output.max(), iduration,
    )

    wav = numpy_to_wave(output.numpy(), model.config.sampling_rate)
    mp3 = wave_to_mp3(wav)
    audio_mimetype = "audio/mp3"

    duration = clock() - T

    # write audio to S3 rather than inlining in the response
    audio_key = write_binary_output(
        message_id=message_id,
        model_type=ModelType.TTS,
        field_name="audio",
        data=mp3,
        mimetype=audio_mimetype,
        bucket=OUTPUT_BUCKET,
    )

    usage = ModelUsageStats(
        duration=duration,
        inference=iduration,
        input_tokens=inputs.input_ids.nelement(),
        output_tokens=0,
        memory_usage=get_memory_usage(),
    )

    response = TTSResponse(
        model=MODELNAME,
        usage=usage,
        language_code=lang_code,
        outputs={
            "audio": OutputReference(path=audio_key, mimetype=audio_mimetype),
        },
    )

    update_metrics(user_id, ModelType.TTS, MODELNAME, response.usage.model_dump())

    return mk_resp(200, response.model_dump(), isBase64Encoded=False)
