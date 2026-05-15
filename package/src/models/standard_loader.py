"""Load HuggingFace models from the EFS cache.

Used by:
  - ECS task handlers at runtime (local_files_only=True by default)
  - The cache-builder EC2 instance during cache population (local_files_only=False)

All loader functions must return a ModelLoaderResult. The processor field is
None for loaders that produce a single pipeline object or use a library (e.g.
sentence-transformers) that handles tokenisation internally.

The standard_loader handles the common AutoTokenizer/AutoProcessor +
AutoModel pattern. Model-type-specific loaders import the correct
transformer classes and delegate to standard_loader.
"""

import logging
import os
from dataclasses import dataclass
from time import perf_counter as clock
from typing import Any
from transformers import BitsAndBytesConfig


logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL") or "INFO")


class ModelNotFoundError(Exception):
    pass


@dataclass
class ModelLoaderResult:
    """Return type for all loader functions.

    processor   -- tokenizer, image processor, or None. None is correct for
                   loaders that use sentence-transformers (which handle
                   tokenisation internally) or that return a single pipeline
                   object such as a diffusers DiffusionPipeline.

    model       -- the loaded model, pipeline, or SentenceTransformer instance.
                   Always present.

    BaseModelHandler.__init__ unpacks this into self.processor and self.model.
    Handlers that need a named alias (e.g. self.pipe) assign it themselves
    after calling super().__init__().
    """

    processor: Any
    model: Any


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
) -> ModelLoaderResult:
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

    # create a quantisation configuration based on parameters
    quantization_config = BitsAndBytesConfig(load_in_4bit=True) if load_in_4bit else None

    try:
        model = ModelClass.from_pretrained(
            modelname,
            cache_dir=cache_dir,
            trust_remote_code=remote_code,
            local_files_only=local_files_only,
            low_cpu_mem_usage=low_cpu_mem_usage,
            quantization_config=quantization_config,
            device_map="auto",
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
        getattr(getattr(model, "config", None), "dtype", "unknown"),
    )

    return ModelLoaderResult(processor=processor, model=model)


def load_txt2audio(modelname: str, cache_dir: str = None, **kwargs) -> ModelLoaderResult:
    """Text-to-audio / music generation.
    NB: there is no handler for this type yet.
    """
    from transformers import AutoModelForTextToWaveform as M
    from transformers import AutoTokenizer as T

    return standard_loader(T, M, modelname, cache_dir=cache_dir, **kwargs)


def load_img2mesh(modelname: str, **kwargs) -> ModelLoaderResult:
    # stub: no compatible model available yet
    raise NotImplementedError("img2mesh loader not implemented")
