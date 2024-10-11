"""txt2speech using facebook mms models

https://dl.fbaipublicfiles.com/mms/misc/language_coverage_mms.html

input must include a language code which must match the model language code in the environment

TODO: creating a mapping from MODELNAME to language code for validation
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

from shared import lambda_event_to_data
from models.cache_model import load_tts

logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL") or "INFO")


MODELNAME = os.environ["MODELNAME"]

T = clock()

tokenizer, model = load_tts(MODELNAME)

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
    try:
        data, mimetype = lambda_event_to_data(event)
    except KeyError as e:
        return {
            "status": "error",
            "status_code": 400,
            "message": "missing key: '%s'" % str(e),
        }

    logger.info("reading '%s' '%s'", str(data), mimetype)

    T = clock()
    inputs = tokenizer(data, return_tensors="pt")

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

    # TODO: convert to mp3 and return
    # import scipy
    # scipy.io.wavfile.write("techno.wav", rate=model.config.sampling_rate, data=output.float().numpy())

    encoded = base64.b64encode(wav)

    logger.info("%ib encoded to %ib", len(wav), len(encoded))

    return {
        "headers": {"Content-Type": "audio/wav"},
        "statusCode": 200,
        "body": encoded,
        "isBase64Encoded": True,
        "stats": {
            "duration": duration,
            "inference": iduration,
            "converion": cduration,
            "input_tokens": inputs.input_ids.nelement(),
        },
    }
