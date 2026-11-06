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
import gzip

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
# TODO: use a .marigoldignore file instead of this hardcode
EXCLUDED_NAMES = {
    ".git", ".hg", ".svn", "__pycache__", ".venv", "venv", "node_modules",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".DS_Store", "dist", "build",
    ".env"
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


# Every member and the gzip header carry this timestamp. Fixed, and not
# taken from SOURCE_DATE_EPOCH, so a local build and a CI build agree
# whatever their environments set.
ARCHIVE_MTIME = 0


def _member_filter(info: tarfile.TarInfo) -> tarfile.TarInfo:
    """Strip host identity and time from archive members.

    Ownership, timestamps and permission bits beyond the read/execute
    distinction are the extracting host's business. An archive carrying
    any of them has different bytes on every machine that builds it.
    """
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    info.mtime = ARCHIVE_MTIME
    info.mode = 0o755 if info.mode & 0o100 else 0o644
    return info


def write_archive(source: Path, archive: Path) -> int:
    """Write an application directory as a .tar.gz. Returns the file count.

    Deterministic: one tree gives one set of bytes. Members are sorted
    and carry no owner or time, and the gzip header holds no filename
    and no time. The digest therefore identifies the content, which is
    what the registry's immutability check compares.

    Members are listed before the archive is opened, so an archive
    written inside its own source directory never contains itself.
    """
    if not (source / APPLICATION_CONFIG_NAME).exists():
        raise FileNotFoundError(f"no {APPLICATION_CONFIG_NAME} in {source}")

    archive.parent.mkdir(parents=True, exist_ok=True)
    members = _members(source)

    with (
        open(archive, "wb") as raw,
        gzip.GzipFile(
            filename="", mode="wb", fileobj=raw,
            compresslevel=9, mtime=ARCHIVE_MTIME,
        ) as gz,
        tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as tar,
    ):
        for path in members:
            tar.add(
                path,
                arcname=path.relative_to(source).as_posix(),
                recursive=False,
                filter=_member_filter,
            )

    return len(members)


def extract_to(archive: Path, target: Path) -> Path:
    """Extract an archive into target and return the application root.

    For reading an archive's contents. Installation uses
    extract_archive, which also copies the archive into the cache.
    """
    with tarfile.open(archive) as tar:
        tar.extractall(target, filter="data")

    return application_root(target)


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
