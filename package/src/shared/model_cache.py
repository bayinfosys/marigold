"""shared/model_cache.py -- measuring the on-disk model cache.

stdlib only. Imported by cli/main.py, which runs on the host from a
package whose dependencies are pyyaml, pydantic and dynawrap.
"""
import stat as _stat
from pathlib import Path


def cache_dir_bytes(path: Path) -> int:
    """Bytes on disk under path, counting each physical file once.

    The HuggingFace layout stores each file once under blobs/ and links to
    it from snapshots/<revision>/. Path.is_file() and Path.stat() both
    follow symlinks, so a plain walk counts every blob once per revision
    referencing it. Sizes accumulate against (st_dev, st_ino), which also
    covers the hardlink layout used where symlinks are unavailable.
    """
    seen: set[tuple[int, int]] = set()
    total = 0

    for child in path.rglob("*"):
        try:
            st = child.lstat()
        except OSError:
            continue

        if not _stat.S_ISREG(st.st_mode):
            continue

        key = (st.st_dev, st.st_ino)

        if key in seen:
            continue

        seen.add(key)
        total += st.st_size

    return total


def model_cache_bytes(model_name: str, cache_path: Path) -> int:
    """Bytes on disk for one model, by its HuggingFace cache directory."""
    cache_dir = cache_path / ("models--" + model_name.replace("/", "--"))

    if not cache_dir.exists():
        return 0

    return cache_dir_bytes(cache_dir)
