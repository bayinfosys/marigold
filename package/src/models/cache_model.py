"""Load HuggingFace models from the EFS cache.

Used by:
  - ECS task handlers at runtime (local_files_only=True by default)
  - The cache-builder EC2 instance during cache population (local_files_only=False)

All loader functions return (processor_or_tokenizer, model) except load_txt2img
which returns a pipeline directly. load_img2mesh is a stub.

The standard_loader handles the common AutoTokenizer/AutoProcessor +
AutoModel pattern. Model-type-specific loaders import the correct
transformer classes and delegate to standard_loader.
"""

import logging
import os
from time import perf_counter as clock

logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL") or "INFO")


class ModelNotFoundError(Exception):
    pass


def standard_loader(
    TokenizerClass,
    ModelClass,
    modelname: str,
    cache_dir: str = None,
    use_fast: bool = False,
    remote_code: bool = False,
    local_files_only: bool = True,
    low_cpu_mem_usage: bool = True,
    load_in_4bit: bool = False,
):
    """Load a tokenizer/processor and a model using the from_pretrained pattern.

    TokenizerClass and ModelClass should be HuggingFace Auto classes, e.g.
    AutoTokenizer and AutoModelForCausalLM.

    load_in_4bit is applied only to the model, not to the tokenizer.
    use_fast and remote_code apply to both.
    """
    T0 = clock()

    try:
        processor = TokenizerClass.from_pretrained(
            modelname,
            cache_dir=cache_dir,
            use_fast=use_fast,
            trust_remote_code=remote_code,
            local_files_only=local_files_only,
        )
    except OSError as e:
        logger.error("'%s' not in local cache [%s]", modelname, str(e))
        raise ModelNotFoundError(modelname) from e
    except Exception as e:
        logger.exception("'%s' tokenizer load failed [%s]", modelname, str(e))
        raise ModelNotFoundError(modelname) from e

    logger.info("loaded '%s' tokenizer in %0.2fs", modelname, clock() - T0)
    T0 = clock()

    try:
        model = ModelClass.from_pretrained(
            modelname,
            cache_dir=cache_dir,
            trust_remote_code=remote_code,
            local_files_only=local_files_only,
            low_cpu_mem_usage=low_cpu_mem_usage,
            load_in_4bit=load_in_4bit,
        )
    except OSError as e:
        logger.error("'%s' not in local cache [%s]", modelname, str(e))
        raise ModelNotFoundError(modelname) from e
    except Exception as e:
        logger.exception("'%s' model load failed [%s]", modelname, str(e))
        raise ModelNotFoundError(modelname) from e

    try:
        model.eval()
    except Exception as e:
        logger.warning("model.eval() failed [%s]", str(e))

    try:
        footprint = model.get_memory_footprint()
    except Exception:
        footprint = 0

    logger.info(
        "loaded '%s' model in %0.2fs footprint=%ib dtype=%s",
        modelname,
        clock() - T0,
        footprint,
        getattr(getattr(model, "config", None), "torch_dtype", "unknown"),
    )

    return processor, model


def load_instruct(modelname: str, **kwargs):
    """Instruction-following / chat models."""
    from transformers import AutoModelForCausalLM as M
    from transformers import AutoTokenizer as T

    return standard_loader(T, M, modelname, **kwargs)


def load_text_embedding(modelname: str, cache_dir: str = None, **kwargs):
    """Text-to-vector embedding via sentence-transformers.

    Returns (tokenizer, SentenceTransformer). The SentenceTransformer handles
    pooling internally so the tokenizer is provided for token-counting only.
    """
    from sentence_transformers import SentenceTransformer as ST
    from transformers import AutoTokenizer as T

    T0 = clock()
    tokenizer = T.from_pretrained(modelname, cache_dir=cache_dir)
    model = ST(modelname, cache_folder=cache_dir)
    logger.info("loaded '%s' in %0.2fs", modelname, clock() - T0)
    return tokenizer, model


def load_image_embedding(modelname: str, cache_dir: str = None, **kwargs):
    """Image-to-vector embedding.

    Uses sentence-transformers for CLIP-compatible models so that image and
    text embeddings share a vector space.

    For non-CLIP checkpoints falls back to AutoImageProcessor + AutoModel.
    """
    from sentence_transformers import SentenceTransformer as ST

    T0 = clock()
    try:
        model = ST(modelname, cache_folder=cache_dir)
        logger.info(
            "loaded '%s' as SentenceTransformer in %0.2fs", modelname, clock() - T0
        )
        return None, model
    except Exception:
        pass

    from transformers import AutoImageProcessor as P
    from transformers import AutoModel as M

    return standard_loader(P, M, modelname, cache_dir=cache_dir, **kwargs)


def load_tts(modelname: str, cache_dir: str = None, **kwargs):
    """Text-to-speech models."""
    from transformers import AutoModelForTextToWaveform as M
    from transformers import AutoTokenizer as T

    if modelname.startswith("parler-tts/"):
        from transformers import AutoModelForSeq2SeqLM as ParlerM

        parler_model = ParlerM.from_pretrained(modelname, cache_dir=cache_dir)
        return None, parler_model

    return standard_loader(T, M, modelname, cache_dir=cache_dir, **kwargs)


def load_txt2audio(modelname: str, cache_dir: str = None, **kwargs):
    """Text-to-audio / music generation."""
    from transformers import AutoModelForTextToWaveform as M
    from transformers import AutoTokenizer as T

    return standard_loader(T, M, modelname, cache_dir=cache_dir, **kwargs)


def load_txt2img(modelname: str, cache_dir: str = None, **kwargs):
    """Text-to-image via diffusers DiffusionPipeline."""
    from diffusers import DiffusionPipeline

    T0 = clock()
    pipe = DiffusionPipeline.from_pretrained(modelname, cache_dir=cache_dir).to("cpu")
    pipe.safety_checker = None
    pipe.requires_safety_checker = False
    logger.info("loaded '%s' pipeline in %0.2fs", modelname, clock() - T0)
    return pipe


def load_img2txt(modelname: str, **kwargs):
    """Image-to-text: captioning, OCR, VQA."""
    from transformers import AutoModelForVision2Seq as M
    from transformers import AutoProcessor as T

    return standard_loader(T, M, modelname, **kwargs)


def load_img2mask(modelname: str, **kwargs):
    """Image segmentation / mask generation."""
    from transformers import AutoModelForMaskGeneration as M
    from transformers import AutoProcessor as T

    return standard_loader(T, M, modelname, **kwargs)


def load_depth(modelname: str, **kwargs):
    """Monocular depth estimation."""
    from transformers import AutoImageProcessor as T
    from transformers import AutoModelForDepthEstimation as M

    return standard_loader(T, M, modelname, **kwargs)


def load_img2mesh(modelname: str, **kwargs):
    # stub: no compatible model available yet
    raise NotImplementedError("img2mesh loader not implemented")


# ---------------------------------------------------------------------------
# CLI entry point (used by the cache-builder and for local testing)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    import sys

    logger = logging.getLogger()
    logger.setLevel(os.getenv("LOG_LEVEL") or "INFO")
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    logger.addHandler(handler)

    _LOADERS = {
        "text-embedding": load_text_embedding,
        "image-embedding": load_image_embedding,
        "instruct": load_instruct,
        "tts": load_tts,
        "txt2img": load_txt2img,
        "img2txt": load_img2txt,
        "img2mask": load_img2mask,
        "depth": load_depth,
        "txt2audio": load_txt2audio,
        "img2mesh": load_img2mesh,
    }

    logger.info("args: '%s'", str(sys.argv))

    if len(sys.argv) > 1:
        model_defs_filename = sys.argv[-1]
        with open(model_defs_filename) as fh:
            model_defs = json.load(fh)
        logger.info("parsed '%s'", model_defs_filename)

        for modelname, model_def in model_defs.items():
            model_type = model_def["model_type"]
            logger.info("caching '%s/%s'", model_type, modelname)
            _LOADERS[model_type](
                modelname=modelname,
                cache_dir="/data/cache/models",
                local_files_only=False,
                low_cpu_mem_usage=False,
            )

        logger.info("all models cached")
        sys.exit(0)

    else:
        TYPE = os.environ["MODEL_TYPE"]
        MODELNAME = os.environ["MODELNAME"]
        CACHE_DIR = os.getenv("CACHE_DIR", "/models")

        assert TYPE in _LOADERS, "'%s' not in %s" % (TYPE, sorted(_LOADERS))

        try:
            _LOADERS[TYPE](
                modelname=MODELNAME,
                cache_dir=CACHE_DIR,
                local_files_only=False,
                low_cpu_mem_usage=False,
            )
        except KeyError as e:
            print("FATAL: unknown loader type '%s'" % str(e))
            sys.exit(1)
