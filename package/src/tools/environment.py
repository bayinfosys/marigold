"""capture information about the worker environment"""

import os
import socket
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version

from shared.db_models import WorkerEnvironment


def _version(package: str) -> str:
    try:
        return version(package)
    except PackageNotFoundError:
        return ""


def collect_environment() -> WorkerEnvironment:
    """Capture what this worker process is running on.

    Called once at startup, before any queue consumer launches. Records
    are append-only: a restart writes a new row rather than updating,
    so an inference resolves to the environment row for its worker with
    the greatest started_at below the inference timestamp.

    Device fields reflect what this process can see after
    CUDA_VISIBLE_DEVICES filtering, which is the number that matters for
    placement and which is otherwise invisible from outside the
    container.
    """
    import torch

    has_cuda = torch.cuda.is_available()
    device_names = []
    device_memory = []

    if has_cuda:
        for index in range(torch.cuda.device_count()):
            props = torch.cuda.get_device_properties(index)
            device_names.append(props.name)
            device_memory.append(props.total_memory)

    driver_version = ""
    try:
        import pynvml

        pynvml.nvmlInit()
        driver_version = pynvml.nvmlSystemGetDriverVersion()
        if isinstance(driver_version, bytes):
            driver_version = driver_version.decode()
    except Exception:
        pass

    return WorkerEnvironment(
        worker_id=os.getenv("MARIGOLD_WORKER_ID") or socket.gethostname(),
        hostname=socket.gethostname(),
        started_at=datetime.now(timezone.utc).isoformat(),
        marigold_version=os.getenv("MARIGOLD_VERSION", "")
        or _version("bayis-marigold"),
        torch_version=_version("torch"),
        diffusers_version=_version("diffusers"),
        transformers_version=_version("transformers"),
        cuda_available=has_cuda,
        cuda_version=torch.version.cuda or "",
        driver_version=driver_version,
        device_count=len(device_names),
        device_names=device_names,
        device_memory_bytes=device_memory,
    )


def resolve_environment(
    backend, table, worker_id: str, at: str
) -> WorkerEnvironment | None:
    """The environment record in force when `at` happened.

    dynawrap queries prefix-match the sort key and have no range
    operator, so this fetches every record for the worker and filters
    in Python. One row per restart makes that cheap; a worker restarted
    daily for a year is 365 rows.
    """
    records = list(backend.query(table, WorkerEnvironment, worker_id=worker_id))
    candidates = [r for r in records if r.started_at <= at]

    if not candidates:
        return None

    return max(candidates, key=lambda r: r.started_at)
