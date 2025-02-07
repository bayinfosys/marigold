"""txt2speech using facebook mms models

https://dl.fbaipublicfiles.com/mms/misc/language_coverage_mms.html

input must include a language code which must match the model language code in the environment

TODO: creating a mapping from MODELNAME to language code for validation
TODO: convert the wav to mp3 for response (requires lame executable and subprocess call)
"""
import os
import io
import logging
import base64
import numpy as np

from time import perf_counter as clock

import torch

import wave

# from scipy.io.wavfile import write as write_wav

from shared import get_userid_from_event, lambda_event_to_data, mk_resp, update_metrics, get_memory_usage
from api.models import ModelType, ModelUsageStats, TTSResponse

from models.cache_model import load_tts, ModelNotFoundError

logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL") or "INFO")


MODELNAME = os.environ["MODELNAME"]

T = clock()

try:
    tokenizer, model = load_tts(MODELNAME)
except ModelNotFoundError as e:
    logger.error("unable to load '%s' [%s]", str(MODELNAME), str(e))
    tokenizer, model = None, None

logger.info("'%s' loaded in '%0.2fs", MODELNAME, (clock() - T))

# logger.info("config: '%s'", str(model.config))


def language_code_from_modelname():
    raise NotImplementedError()


def wave_to_mp3(wav):
    """convert a wave format to mp3"""
    raise NotImplementedError()


def numpy_to_wave(arr, sample_rate: int):
    """convert a numpy array to a wave bytes"""
    sc = np.int16(arr * 32768)

    logger.info(
        "scaled '%s.%s' [%0.3f->%0.3f] to '%s.%s' [%d->%d]",
        str(arr.dtype),
        str(arr.shape),
        arr.min(),
        arr.max(),
        str(sc.dtype),
        str(sc.shape),
        sc.min(),
        sc.max(),
    )

    with io.BytesIO() as f:
        with wave.open(f, "wb") as wf:
            wf.setnchannels(1)  # Assuming mono audio, change to 2 if stereo
            wf.setsampwidth(2)  # 16-bit PCM
            wf.setframerate(sample_rate)
            wf.writeframes(sc.tobytes())
        return f.getvalue()


def lambda_handler(event, context):
    """run the data through the model"""
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

    logger.info("reading '%s' '%s'", str(data), mimetype)

    try:
        text = data["input"]
    except KeyError as e:
        logger.error("'text' not found in '%s' [%s]", str(data), str(e))
        return mk_resp(400, {"status": "error", "message": "missing 'text' in 'input'"})

    try:
        lang_code = data["lang_code"]
    except KeyError as e:
        logger.warning("'lang_code' not specified in '%s' [%s]", str(data), str(e))
        lang_code = "en-GB"

    logger.info("tts over: '%s' [%i]", str(text), len(text))

    T = clock()
    inputs = tokenizer(text, return_tensors="pt")

    T1 = clock()
    with torch.no_grad():
        output = model(**inputs).waveform
    iduration = clock() - T1

    logger.info(
        "completed '%s.%s' [%0.4f->%0.4f] in %0.2fs",
        str(output.shape),
        str(output.dtype),
        output.min(),
        output.max(),
        iduration,
    )

    T2 = clock()
    wav = numpy_to_wave(output.numpy(), model.config.sampling_rate)
    cduration = clock() - T2

    logger.info(
        "converted '%s.%s' %shz in %0.2fs",
        str(output.shape),
        str(output.dtype),
        str(model.config.sampling_rate),
        cduration,
    )

    duration = clock() - T

    logger.info("wav: '%s' [%i]", str(type(wav)), len(wav))

    # convert to mp3 and return
    # import scipy
    # scipy.io.wavfile.write("techno.wav", rate=model.config.sampling_rate, data=output.float().numpy())

    audio = base64.b64encode(wav).decode()

    logger.info("%ib encoded to %ib", len(wav), len(audio))

    usage = ModelUsageStats(
        duration=duration,
        inference=iduration,
        #conversion=cduration,
        input_tokens=inputs.input_ids.nelement(),
        output_tokens=0,
        memory_usage=get_memory_usage()
    )

    # FIXME: if len(audio) > SOME_THRESHOLD write to s3 and return a link
    response = TTSResponse(
        model=MODELNAME,
        usage=usage,
        lang_code=lang_code,
        data=audio,
        mimetype="audio/wav"
    )

    update_metrics(user_id, ModelType.TTS, MODELNAME, response.usage.model_dump())

    return mk_resp(200, response.model_dump(), isBase64Encoded=False)
