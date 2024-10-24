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


def load_instruct(
    modelname: str,
    cache_dir: str = None,
    load_in_4bit: bool = False,
    use_fast: bool = False,
    remote_code: bool = False,
    local_files_only: bool = True,
    low_cpu_mem_usage: bool = True,
):
    T0 = clock()
    from transformers import AutoTokenizer as T

    logger.info("imported transformers.toks in %0.2fs", (clock() - T0))

    T0 = clock()
    from transformers import AutoModelForCausalLM as M

    logger.info("import transformers.model in %0.2fs", (clock() - T0))

    logger.info("loading '%s' from '%s'", modelname, cache_dir)

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
        "loaded '%s'.model in %0.2fs into %ib",
        modelname,
        (clock() - T0),
        cbsize,
    )

    return t, m


def load_text_embedding(modelname: str, cache_dir: str = None, **kwargs):
    from sentence_transformers import SentenceTransformer as ST

    T0 = clock()
    m = ST(modelname, cache_folder=cache_dir)

    logger.info(
        "loaded '%s'.model in %0.2fs",
        modelname,
        (clock() - T0),
    )

    return m


def load_image_embedding(modelname: str, cache_dir: str = None, **kwargs):
    from transformers import AutoImageProcessor as P
    from transformers import AutoModel as ST

    P.from_pretrained(modelname, cache_dir=cache_dir)
    ST.from_pretrained(modelname, cache_dir=cache_dir)


def load_tts(modelname: str, cache_dir: str = None, **kwargs):
    from transformers import VitsModel as M
    from transformers import AutoTokenizer as T

    t = T.from_pretrained(modelname, cache_dir=cache_dir)
    m = M.from_pretrained(modelname, cache_dir=cache_dir)

    return t, m


def load_txt2img(modelname: str, cache_dir: str = None, **kwargs):
    from diffusers import DiffusionPipeline as PPL

    pipe = PPL.from_pretrained(modelname, cache_dir=cache_dir).to("cpu")
    pipe.safety_checker = None
    pipe.requires_safety_checker = False

    return pipe


def load_img2txt(
    modelname: str,
    cache_dir: str = None,
    load_in_4bit: bool = False,
    use_fast: bool = False,
    remote_code: bool = False,
    local_files_only: bool = True,
    low_cpu_mem_usage: bool = True,
):
    T0 = clock()
    #from transformers import AutoProcessor as T
    #from transformers import AutoTokenizer as T
    from transformers import DonutProcessor as T

    logger.info("imported transformers.proc in %0.2fs", (clock() - T0))

    T0 = clock()
    #from transformers import AutoModelForPreTraining as M
    #from transformers import AutoModel as M
    from transformers import VisionEncoderDecoderModel as M

    logger.info("import transformers.model in %0.2fs", (clock() - T0))

    logger.info("loading '%s' from '%s'", modelname, cache_dir)

    try:
        p = T.from_pretrained(
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
        "loaded '%s'.model in %0.2fs into %ib",
        modelname,
        (clock() - T0),
        cbsize,
    )

    return p, m


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
                low_cpu_mem_usage=False
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
