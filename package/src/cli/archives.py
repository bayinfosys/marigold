"""Application archives: writing, digesting and extracting them.

An archive is a .tar.gz of an application directory. This module turns
a directory into an archive and an archive into an extracted tree in
the cache. It knows nothing about application names or the installed
index; cli.applications decides what those trees are.

Archives are copied into the cache and extracted there, because
containers mount the result and outlive the command that started them.
"""

import hashlib
import shutil
import tarfile

from pathlib import Path

from cli.config import APPLICATION_CONFIG_NAME
from cli.paths import (
    archives_dir,
    cache_dir_from_system_config,
    ensure_cache_layout,
    extracted_applications_dir,
)

ARCHIVE_SUFFIXES = (".tar.gz", ".tgz", ".marigold")

# Never archived: caches, VCS metadata, virtualenvs, build output.
EXCLUDED_NAMES = {
    ".git", ".hg", ".svn", "__pycache__", ".venv", "venv", "node_modules",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".DS_Store", "dist", "build",
}
EXCLUDED_SUFFIXES = (".pyc", ".pyo") + ARCHIVE_SUFFIXES


def is_archive(target: str) -> bool:
    return target.endswith(ARCHIVE_SUFFIXES)


def archive_digest(archive: Path) -> str:
    """sha256 of an archive, read in chunks rather than in one piece."""
    digest = hashlib.sha256()

    with open(archive, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)

    return digest.hexdigest()


def _members(source: Path) -> list[Path]:
    """Files to archive, sorted, excluding caches and build output."""
    members = []

    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)

        if any(part in EXCLUDED_NAMES for part in relative.parts):
            continue
        if path.name.endswith(EXCLUDED_SUFFIXES):
            continue
        if not path.is_file():
            continue

        members.append(path)

    return members


def _member_filter(info: tarfile.TarInfo) -> tarfile.TarInfo:
    """Strip host identity from archive members.

    Ownership and permission bits beyond the read/execute distinction
    are the extracting host's business, and an archive carrying the
    builder's uid extracts differently for everyone else.
    """
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    info.mode = 0o755 if info.mode & 0o100 else 0o644
    return info


def write_archive(source: Path, archive: Path) -> int:
    """Write an application directory as a .tar.gz. Returns the file count.

    Members are listed before the archive is opened, so an archive
    written inside its own source directory never contains itself.
    """
    if not (source / APPLICATION_CONFIG_NAME).exists():
        raise FileNotFoundError(f"no {APPLICATION_CONFIG_NAME} in {source}")

    archive.parent.mkdir(parents=True, exist_ok=True)
    members = _members(source)

    with tarfile.open(archive, "w:gz") as tar:
        for path in members:
            tar.add(
                path,
                arcname=str(path.relative_to(source)),
                filter=_member_filter,
            )

    return len(members)


def application_root(extracted: Path) -> Path:
    """The application root inside an extracted archive.

    Archives are written both ways: files at the top level, or one
    directory containing them (app-1.0/marigold.toml). Both resolve
    here, so neither is an archiving error.
    """
    if (extracted / APPLICATION_CONFIG_NAME).exists():
        return extracted

    children = [c for c in extracted.iterdir() if not c.name.startswith(".")]

    if len(children) == 1 and children[0].is_dir():
        if (children[0] / APPLICATION_CONFIG_NAME).exists():
            return children[0]

    raise ValueError(
        f"no {APPLICATION_CONFIG_NAME} at the root of the extracted "
        f"application ({extracted})"
    )


def extract_archive(archive: Path) -> tuple[Path, Path, str, Path]:
    """Copy an archive into the cache and extract it there.

    Returns (extraction directory, application root, digest, kept
    archive). The first two differ when the archive holds one top-level
    directory; uninstall removes the extraction directory, so both are
    recorded.

    Content-addressed: the same archive always resolves to the same
    root, is extracted once, and stop/status/logs reach the tree start
    used.

    The cache location comes from the system config alone: the
    application config is inside the archive and cannot be read before
    it exists.
    """
    cache_dir = cache_dir_from_system_config()
    ensure_cache_layout(cache_dir)

    digest = archive_digest(archive)

    kept = archives_dir(cache_dir) / f"{digest}.tar.gz"
    if not kept.exists():
        shutil.copy2(archive, kept)

    target = extracted_applications_dir(cache_dir) / digest[:16]

    if target.exists():
        return target, application_root(target), digest, kept

    staging = target.with_name(f"{target.name}.partial")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)

    try:
        with tarfile.open(kept) as tar:
            # filter="data" refuses absolute paths, parent traversal,
            # links pointing out of the tree, devices and setuid bits.
            tar.extractall(staging, filter="data")
        staging.rename(target)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    return target, application_root(target), digest, kept
