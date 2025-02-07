"""cache a hugging face model

assumes the host env has a network connection

This is used to cache models (as an ec2 startup script)
and also load the models at runtime from the cache.

NB: this laods models at runtime, see these threads for HF loading optimization issues:
https://huggingface.co/mosaicml/mpt-7b-instruct/discussions/6
"""
import os
import logging

from time import perf_counter as clock


logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL") or "INFO")


class ModelNotFoundError(Exception):
    pass


def standard_loader(
    T,
    M,
    modelname,
    cache_dir: str = None,
    load_in_4bit: bool = False,
    use_fast: bool = False,
    remote_code: bool = False,
    local_files_only: bool = True,
    low_cpu_mem_usage: bool = True,
):
    """load a standard T.from_pretrained and M.from_pretrained
    where T is one of AutoTokenizer, AutoImageProcess etc
    and M is one of AutoModel, AutoModelForDepthEstimation etc
    """
    # can't do these asserts without needing the type imports, can we check names?
    # assert T in (AutoImageProcessor, AutoTokenizer)
    # assert M in (AutoModelForDepthEstimation, AutoModelForCausalLM)
    T0 = clock()

    try:
        t = T.from_pretrained(
            modelname,
            cache_dir=cache_dir,
            load_in_4bit=load_in_4bit,
            use_fast=use_fast,
            trust_remote_code=remote_code,
            local_files_only=local_files_only,
        )
    except OSError as e:
        logger.error("'%s' not in local caache [%s]", modelname, str(e))
        raise ModelNotFoundError(modelname) from e
    except Exception as e:
        logger.exception("'%s' load tokenizer failed [%s]", modelname, str(e))
        raise ModelNotFoundError(modelname) from e

    logger.info("loaded '%s'.tok in %0.2fs", modelname, (clock() - T0))

    T0 = clock()

    # NB: do not set the dtype for CPU loading (only float32 is performant)
    try:
        m = M.from_pretrained(
            modelname,
            cache_dir=cache_dir,
            load_in_4bit=load_in_4bit,
            trust_remote_code=remote_code,
            local_files_only=local_files_only,
            low_cpu_mem_usage=low_cpu_mem_usage,
        )
    except OSError as e:
        logger.error("'%s' not in local caache [%s]", modelname, str(e))
        raise ModelNotFoundError(modelname) from e
    except Exception as e:
        logger.exception("'%s' load model failed [%s]", modelname, str(e))
        raise ModelNotFoundError(modelname) from e

    try:
        m.eval()
    except Exception as e:
        logger.error("m.eval() failed [%s]", str(e))

    try:
        cbsize = m.get_memory_footprint()
    except Exception as e:
        logger.error("m.get_memory_footprint() failed [%s]", str(e))
        cbsize = 0

    logger.info(
        "loaded '%s'.model in %0.2fs into %ib [%s]",
        modelname,
        (clock() - T0),
        cbsize,
        m.config.torch_dtype,
    )

    return t, m


def load_instruct(modelname: str, **kwargs):
    """instruct models AKA chatbots"""
    from transformers import AutoTokenizer as T
    from transformers import AutoModelForCausalLM as M

    return standard_loader(T, M, modelname, **kwargs)


def load_text_embedding(modelname: str, cache_dir: str = None, **kwargs):
    """text-to-vector do text embeddings
    NB: we should avoid using the sentence-transformers lib directly, and use
        the tokenizer/model setup so we can replicate the standard flow/metrics
    NB: SentenceTransformer has no .from_pretrained method
    """
    from transformers import AutoTokenizer as T
    from sentence_transformers import SentenceTransformer as ST

    T0 = clock()
    t = T.from_pretrained(modelname, cache_dir=cache_dir)
    m = ST(modelname, cache_folder=cache_dir)

    logger.info(
        "loaded '%s'.model in %0.2fs",
        modelname,
        (clock() - T0),
    )

    return t, m


def load_image_embedding(modelname: str, cache_dir: str = None, **kwargs):
    """image-to-vector do image embeddings
    NB: we use sentence transformers to do clip models so we can support text search over images
    """
    from transformers import AutoImageProcessor as P
    from transformers import AutoModel as M

    return standard_loader(P, M, modelname, **kwargs)


def load_tts(modelname: str, cache_dir: str = None, **kwargs):
    """text-to-speech"""
    from transformers import AutoModelForTextToWaveform as M
    from transformers import AutoModelForSeq2SeqLM
    from transformers import AutoTokenizer as T

    if modelname.startswith("parler-tts/"):
        return None, AutoModelForSeq2SeqLM.from_pretrained(modelname, cache_dir=cache_dir)
    else:
        return standard_loader(T, M, modelname, **kwargs)


def load_txt2audio(modelname: str, cache_dir: str = None, **kwargs):
    """txt to audio/music"""
    from transformers import AutoTokenizer as T
    from transformers import AutoModelForTextToWaveform as M

    return standard_loader(T, M, modelname, **kwargs)


def load_txt2img(modelname: str, cache_dir: str = None, **kwargs):
    """text-to-image are image generators"""
    from diffusers import DiffusionPipeline as PPL

    pipe = PPL.from_pretrained(modelname, cache_dir=cache_dir).to("cpu")
    pipe.safety_checker = None
    pipe.requires_safety_checker = False

    return pipe


def load_img2txt(modelname: str, **kwargs):
    """image-to-text models do captions, ocr, etc"""
    from transformers import AutoProcessor as T
    from transformers import AutoModelForVision2Seq as M

    return standard_loader(T, M, modelname, **kwargs)


def load_depth(modelname: str, **kwargs):
    """depth estimator"""
    from transformers import AutoImageProcessor as T
    from transformers import AutoModelForDepthEstimation as M

    return standard_loader(T, M, modelname, **kwargs)


def load_img2mesh(modelname: str, **kwargs):
    pass


if __name__ == "__main__":
    import sys
    import json

    logger = logging.getLogger()
    logger.setLevel(os.getenv("LOG_LEVEL") or "INFO")
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    cachers = {
        "text-embedding": load_text_embedding,
        "image-embedding": load_image_embedding,
        "instruct": load_instruct,
        "tts": load_tts,
        "txt2img": load_txt2img,
        "img2txt": load_img2txt,
        "depth": load_depth,
        "txt2audio": load_txt2audio,
        "img2mesh": load_img2mesh
    }

    logger.info("args: '%s'", str(sys.argv))

    if len(sys.argv) > 1:
        model_defs_filename = sys.argv[-1]
        model_defs = json.load(open(model_defs_filename))
        logger.info("parsed '%s'", model_defs_filename)

        for modelname, model_def in model_defs.items():
            logger.info("caching '%s/%s'", model_def["model_type"], modelname)
            cachers[model_def["model_type"]](
                modelname=modelname,
                cache_dir="/data/cache/models",
                load_in_4bit=False,
                use_fast=False,
                remote_code=False,
                local_files_only=False,
                low_cpu_mem_usage=False,
            )

        logger.info("all models cached")

        sys.exit(0)

    else:
        # load from env
        TYPE = os.environ["MODEL_TYPE"]
        MODELNAME = os.environ["MODELNAME"]
        CACHE_DIR = os.getenv("CACHE_DIR", "/models")
        LOAD_IN_4BIT = bool(int(os.getenv("LOAD_IN_4BIT") or False))
        USE_FAST = bool(int(os.getenv("USE_FAST") or False))  # tokenizer
        REMOTE_CODE = bool(int(os.getenv("REMOTE_CODE") or False))
        LOCAL_FILES_ONLY = bool(
            os.getenv("LOCAL_FILES_ONLY", "False").lower() in ("true", "1", "t")
        )
        LOW_CPU_MEM_USAGE = bool(
            os.getenv("LOW_CPU_MEM_USAGE", "False").lower() in ("true", "1", "t")
        )

        assert TYPE in cachers, "%s not in %s" % (TYPE, str(list(cachers.keys())))

        try:
            cachers[TYPE](
                modelname=MODELNAME,
                cache_dir=CACHE_DIR,
                load_in_4bit=LOAD_IN_4BIT,
                use_fast=USE_FAST,
                remote_code=REMOTE_CODE,
                local_files_only=LOCAL_FILES_ONLY,
                low_cpu_mem_usage=LOW_CPU_MEM_USAGE,
            )
        except KeyError as e:
            print("FATAL: unknown cacher type '%s'" % str(e))
