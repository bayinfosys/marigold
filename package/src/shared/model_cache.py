"""shared/model_cache.py -- the on-disk model cache: names and sizes.

The one place that knows Hugging Face's cache layout. stdlib only:
imported by the CLI on the host, whose dependencies are pyyaml, pydantic
and dynawrap, and by the cache container.

Each model is a directory models--<org>--<name> holding blobs/,
snapshots/<revision>/ and refs/main. Files in snapshots/ are links into
blobs/. Recent huggingface_hub versions also keep a shared store,
blobs/<xx>/<sha256> at the cache root, and a model's own blobs/ entries
link into it. Sizes follow every link and count each file once.

Sizes are bytes; GB is 1e9 bytes, the unit every report uses.
"""
import os
import stat as _stat

from pathlib import Path

GB = 1e9

_PREFIX = "models--"


def model_dir_name(model_name: str) -> str:
    """'org/name' -> 'models--org--name'."""
    return _PREFIX + model_name.replace("/", "--")


def model_name_from_dir(dirname: str) -> str | None:
    """'models--org--name' -> 'org/name'; None for anything else."""
    if not dirname.startswith(_PREFIX):
        return None

    name = dirname[len(_PREFIX):].replace("--", "/")
    return name if "/" in name else None


def cached_models(models_dir: Path) -> dict[str, Path]:
    """model name -> directory, for every model directory in the cache."""
    if not models_dir.is_dir():
        return {}

    found = {}

    for entry in sorted(models_dir.iterdir()):
        name = model_name_from_dir(entry.name)
        if name and entry.is_dir():
            found[name] = entry

    return found


def files_bytes(path: Path, seen: set | None = None) -> int:
    """Bytes of the files under path, following links, each file once.

    Links are followed to their targets, wherever those are, so a model
    whose weights sit in the shared store is measured in full. Targets
    are counted against (st_dev, st_ino): pass one seen set across
    several calls to count a file shared between models once in total.
    """
    seen = set() if seen is None else seen
    total = 0

    for dirpath, _, filenames in os.walk(path):
        for filename in filenames:
            try:
                st = os.stat(Path(dirpath) / filename)
            except OSError:
                continue  # a dangling link

            if not _stat.S_ISREG(st.st_mode):
                continue

            key = (st.st_dev, st.st_ino)
            if key in seen:
                continue

            seen.add(key)
            total += st.st_size

    return total


def model_bytes(model_name: str, models_dir: Path, seen: set | None = None) -> int:
    """Bytes on disk for one model; 0 when it is not cached."""
    path = models_dir / model_dir_name(model_name)
    return files_bytes(path, seen) if path.is_dir() else 0


def model_revision(model_name: str, models_dir: Path) -> str | None:
    """The revision refs/main points at, or None."""
    ref = models_dir / model_dir_name(model_name) / "refs" / "main"

    try:
        return ref.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def model_files(model_name: str, models_dir: Path) -> int:
    """Files in the model's current snapshot."""
    revision = model_revision(model_name, models_dir)

    if revision is None:
        return 0

    snapshot = models_dir / model_dir_name(model_name) / "snapshots" / revision
    return sum(len(files) for _, _, files in os.walk(snapshot))
