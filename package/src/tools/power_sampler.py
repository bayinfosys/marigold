import logging
import threading
from contextlib import contextmanager

import pynvml
import torch

logger = logging.getLogger(__name__)


class ModelVRAMError(Exception):
    """Raised when a model cannot fit entirely in GPU VRAM."""
    pass


def get_memory_usage() -> int:
    import resource
    return 1 + int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0)


def get_vram_usage() -> int:
    if not torch.cuda.is_available():
        return 0
    try:
        return sum(torch.cuda.memory_allocated(i) for i in range(torch.cuda.device_count()))
    except Exception:
        return 0


def get_vram_state() -> dict:
    """Capture current VRAM state across every visible GPU device.

    Returns zeros if CUDA is unavailable or the query fails.
    Queries fresh each call so values reflect current state at
    the point of measurement. Aggregates across all devices -- a
    single mem_get_info(0) call missed anything resident on a
    second GPU, the same gap get_vram_usage had before it summed
    across devices.
    """
    if not torch.cuda.is_available():
        return {"free_vram_b": 0, "total_vram_b": 0, "usable_vram_b": 0}
    try:
        free_total = 0
        total_total = 0
        for i in range(torch.cuda.device_count()):
            free, total = torch.cuda.mem_get_info(i)
            free_total += free
            total_total += total
        usable = int(free_total * 0.90)
        return {"free_vram_b": free_total, "total_vram_b": total_total, "usable_vram_b": usable}
    except Exception as e:
        logger.warning("failed to get VRAM info: %s", e)
        return {"free_vram_b": 0, "total_vram_b": 0, "usable_vram_b": 0}


# ---------------------------------------------------------------------------
# Parameter extraction -- one function per model backing type
# ---------------------------------------------------------------------------

def _params_from_transformer(model) -> list:
    """Extract parameters from a transformers-backed model.

    Expects model.model to be an nn.Module with a named_parameters() method,
    which covers AutoModel, AutoModelForCausalLM, AutoModelForVision2Seq,
    and the sentence-transformers wrappers used by text-embedding models.
    """
    return list(model.model.named_parameters())


def _params_from_diffusion_pipeline(model) -> list:
    """Extract parameters from a diffusers DiffusionPipeline.

    A DiffusionPipeline is a composite object. Its sub-components are
    accessible via .components, which returns a dict of name to object.
    Only components that are nn.Module instances carry parameters.

    Covers StableDiffusionPipeline, StableDiffusionXLPipeline,
    StableDiffusion3Pipeline, FluxPipeline, and any pipeline whose
    components follow the standard diffusers pattern.
    """
    params = []
    for component_name, component in model.model.components.items():
        if isinstance(component, torch.nn.Module):
            for param_name, param in component.named_parameters():
                params.append((f"{component_name}.{param_name}", param))
    return params


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def _extract_named_parameters(model_name: str, model) -> list:
    """Dispatch to the appropriate parameter extractor for model.model.

    Raises NotImplementedError for unrecognised backing types so that new
    model types are caught explicitly rather than silently producing an
    incorrect VRAM check.

    To add support for a new backing type: implement a _params_from_*
    function above and add an isinstance branch here.
    """
    from diffusers import DiffusionPipeline

    if isinstance(model.model, DiffusionPipeline):
        return _params_from_diffusion_pipeline(model)

    if isinstance(model.model, torch.nn.Module):
        return _params_from_transformer(model)

    raise NotImplementedError(
        "check_model_vram: unhandled model backing type '%s' for '%s'. "
        "Implement a _params_from_* extractor in power_sampler.py and add "
        "an isinstance branch in _extract_named_parameters."
        % (type(model.model).__name__, model_name)
    )


# ---------------------------------------------------------------------------
# VRAM check
# ---------------------------------------------------------------------------

def check_model_vram(model_name: str, model):
    """Raise ModelVRAMError if any model parameters were offloaded to CPU.

    Dispatches parameter extraction via _extract_named_parameters. Raises
    NotImplementedError for unhandled model backing types.

    Note: this only distinguishes "cpu"/"meta" from "cuda" -- it does not
    check which CUDA device a parameter landed on, since a tensor split
    across cuda:0 and cuda:1 is equally fine for this check. It exists to
    catch CPU/disk offload, not to report device placement; get_vram_state
    and get_vram_usage are the multi-GPU-aware reporting functions.
    """
    named_params = _extract_named_parameters(model_name, model)

    cpu_params = [
        name for name, param in named_params
        if param.device.type in ("cpu", "meta")
    ]

    if not cpu_params:
        return

    gpu_params = [
        name for name, param in named_params
        if param.device.type in ("cuda",)
    ]

    gpu_bytes = sum(
        param.numel() * param.element_size()
        for _, param in named_params
        if param.device.type in ("cuda",)
    )
    cpu_bytes = sum(
        param.numel() * param.element_size()
        for _, param in named_params
        if param.device.type in ("cpu", "meta")
    )

    vram = get_vram_state()

    logger.critical(
        "'%s' did not fit on GPU -- %d tensors on CPU (%.1fGB) "
        "%d on GPU (%.1fGB) vram_free=%.1fGB vram_total=%.1fGB",
        model_name,
        len(cpu_params),
        cpu_bytes / 1024**3,
        len(gpu_params),
        gpu_bytes / 1024**3,
        vram["free_vram_b"] / 1024**3,
        vram["total_vram_b"] / 1024**3,
    )

    raise ModelVRAMError(model_name)


class PowerSampler:
    """Background NVML sampler, scoped to one request via context manager.

    Mirrors _heartbeat/_heartbeat_context's thread+Event pattern, with a
    sub-second interval instead of visibility_timeout's, and a read instead
    of a write. Captures device state at the time of the request, not a
    property of the request itself -- under concurrency > 1 on a worker
    that ran requests in parallel, a sample reflects whatever both GPUs
    were doing at that instant, the same caveat as vram_usage_bytes.

    Holds one NVML handle per visible device and sums power draw across
    all of them each tick -- a single-handle reading previously missed
    anything drawn by a second GPU entirely.
    """

    def __init__(self, interval: float = 0.1):
        self._interval = interval
        self._stop = threading.Event()
        self._readings: list[int] = []  # milliwatts, summed across all GPUs per tick
        self._nvml_handles: list = []

        if torch.cuda.is_available():
            try:
                pynvml.nvmlInit()
                self._nvml_handles = [
                    pynvml.nvmlDeviceGetHandleByIndex(i)
                    for i in range(torch.cuda.device_count())
                ]
            except Exception as e:
                logger.warning("NVML init failed, power sampling disabled: %s", e)

    def _run(self):
        while not self._stop.wait(timeout=self._interval):
            if self._nvml_handles:
                try:
                    total_mw = sum(
                        pynvml.nvmlDeviceGetPowerUsage(handle)
                        for handle in self._nvml_handles
                    )
                    self._readings.append(total_mw)
                except Exception as e:
                    logger.warning("power sample failed: %s", e)

    @property
    def peak_watts(self) -> float:
        return max(self._readings, default=0) / 1000.0 if self._readings else 0.0

    @property
    def mean_watts(self) -> float:
        return (
            (sum(self._readings) / len(self._readings) / 1000.0)
            if self._readings
            else 0.0
        )

    @contextmanager
    def sample(self):
        """One sampling window per call -- safe to call once per message
        on a long-lived instance. Resets readings and the stop flag each
        time; without that, state from message 1 leaks into every
        message after it.
        """
        self._readings = []
        self._stop.clear()

        if torch.cuda.is_available():
            for i in range(torch.cuda.device_count()):
                torch.cuda.reset_peak_memory_stats(i)
            self.vram_usage = get_vram_usage()
        else:
            self.vram_usage = 0

        thread = threading.Thread(target=self._run, daemon=True)
        thread.start()

        try:
            yield self
        finally:
            self._stop.set()
            thread.join(timeout=2)

        if torch.cuda.is_available():
            self.max_vram_usage = sum(
                torch.cuda.max_memory_allocated(i)
                for i in range(torch.cuda.device_count())
            )
        else:
            self.max_vram_usage = 0

    def as_usage_fields(self) -> dict:
        """The one place that maps sampled readings onto ModelUsageStats field
        names. Adding a metric means adding it here and to ModelUsageStats --
        nowhere else needs to change.
        """
        return {
            "power_watts_peak":    self.peak_watts,
            "power_watts_mean":    self.mean_watts,
            "vram_usage_bytes_peak": self.max_vram_usage,
            "vram_usage_bytes":    self.vram_usage,
            "memory_usage":        get_memory_usage(),
        }

    def shutdown(self):
        """nvmlShutdown is expensive; called per model load/unload, not per
        inference request. It shuts down the NVML library as a whole, not
        per-handle, so this is unaffected by holding multiple handles.
        """
        if self._nvml_handles:
            try:
                pynvml.nvmlShutdown()
            except Exception:
                pass
