"""
Container build diagnostic.
Run at the end of a Docker build (RUN python build_info.py) or on first start.
Exits non-zero if CUDA is not available in a GPU-tagged build.
"""

import os
import platform
import subprocess
import sys


def _cmd(args):
    try:
        return subprocess.check_output(args, stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return "unavailable"


def _torch_info():
    try:
        import torch
        cuda_available = torch.cuda.is_available()
        info = {
            "torch":        torch.__version__,
            "cuda_built":   torch.version.cuda or "none",
            "cudnn_built":  str(torch.backends.cudnn.version()) if torch.backends.cudnn.is_available() else "none",
            "cuda_runtime": "available" if cuda_available else "not available",
        }
        if cuda_available:
            info["device_count"] = torch.cuda.device_count()
            info["device_0"]     = torch.cuda.get_device_name(0)
            mem = torch.cuda.get_device_properties(0).total_memory
            info["device_0_vram_gb"] = f"{mem / (1024 ** 3):.1f}"
        return info, cuda_available
    except ImportError:
        return {"torch": "not installed"}, False


def _transformers_version():
    try:
        import transformers
        return transformers.__version__
    except ImportError:
        return "not installed"


def _numpy_version():
    try:
        import numpy
        return numpy.__version__
    except ImportError:
        return "not installed"


def main():
    gpu_enabled = bool(os.environ.get("GPU_ENABLED") or False)

    print("=" * 48)
    print("container build info")
    print("=" * 48)
    print(f"image_tag    : {os.environ.get('IMAGE_TAG', 'unset')}")
    print(f"gpu_enabled  : {os.environ.get('GPU_ENABLED', 'unset')}")
    print(f"python       : {platform.python_version()}")
    print(f"platform     : {platform.platform()}")
    print(f"nvidia-smi   : {_cmd(['nvidia-smi', '--query-gpu=name,driver_version,memory.total', '--format=csv,noheader'])}")

    torch_info, cuda_available = _torch_info()
    for k, v in torch_info.items():
        print(f"{k:<17}: {v}")

    print(f"transformers     : {_transformers_version()}")
    print(f"numpy            : {_numpy_version()}")
    print("=" * 48)

    if gpu_enabled and not cuda_available:
        print("ERROR: GPU_ENABLED=1 but torch.cuda.is_available() is False")
        sys.exit(1)


if __name__ == "__main__":
    main()
