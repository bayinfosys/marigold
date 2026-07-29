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

import torch
from transformers import BitsAndBytesConfig

from shared.sns_models import EventType, LifecycleEvent

logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL") or "INFO")


class ModelNotFoundError(Exception):
    pass


# ---------------------------------------------------------------------------
# VRAM utilities
# ---------------------------------------------------------------------------


def get_max_memory() -> dict | None:
    """Returns max_memory dict for device_map='auto', or None for CPU.

    Iterates all available GPU devices. Uses usable VRAM (90% of free)
    to leave headroom for activations and KV cache.
    """
    if not torch.cuda.is_available():
        return None

    max_memory = {}
    for i in range(torch.cuda.device_count()):
        try:
            free, _ = torch.cuda.mem_get_info(i)
            max_memory[i] = int(free * 0.90)
        except Exception as e:
            logger.warning("failed to get VRAM info for device %d: %s", i, e)

    return max_memory or None


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


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
    model_size_bytes: int = 0
    load_time_ms: int = 0


# ---------------------------------------------------------------------------
# Standard loader
# ---------------------------------------------------------------------------


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
    **model_kwargs
) -> ModelLoaderResult:
    """Load a tokenizer/processor and a model using the from_pretrained pattern.

    TokenizerClass and ModelClass should be HuggingFace Auto classes, e.g.
    AutoTokenizer and AutoModelForCausalLM.

    load_in_4bit is applied only to the model, not to the tokenizer.
    use_fast and remote_code apply to both.

    Any additional keyword arguments (model_kwargs) are passed straight
    through to ModelClass.from_pretrained(), e.g. attn_implementation.
    They have no effect on the tokenizer load.
    """
    # double check the envvars here, so we don't rely on the caller.
    use_fast = use_fast or os.getenv("USE_FAST", "").lower() in ("1", "true")
    remote_code = remote_code or os.getenv("TRUST_REMOTE_CODE", "").lower() == "true"
    load_in_4bit = load_in_4bit or os.getenv("LOAD_IN_4BIT", "").lower() in ("1", "true")
    low_cpu_mem_usage = low_cpu_mem_usage or os.getenv("LOW_CPU_MEM_USAGE", "true").lower() in ("1", "true")

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

    # quantise the model as required
    quantization_config = BitsAndBytesConfig(load_in_4bit=True, llm_int8_enable_fp32_cpu_offload=True) if load_in_4bit else None

    try:
        model = ModelClass.from_pretrained(
            modelname,
            cache_dir=cache_dir,
            trust_remote_code=remote_code,
            local_files_only=local_files_only,
            low_cpu_mem_usage=low_cpu_mem_usage,
            quantization_config=quantization_config,
            device_map="auto",
            max_memory=get_max_memory(),
            **model_kwargs,
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

    load_time = int((clock() - T0) * 1000)

    logger.info(
        "loaded '%s' model in %0.2fs footprint=%ib dtype=%s",
        modelname,
        load_time/1000.,
        footprint,
        getattr(getattr(model, "config", None), "dtype", "unknown"),
    )

    return ModelLoaderResult(processor=processor, model=model, model_size_bytes=footprint, load_time_ms=load_time)


# ---------------------------------------------------------------------------
# Type-specific loaders
# ---------------------------------------------------------------------------


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
