"""Application archives: writing, digesting and extracting them.

An archive is a .tar.gz of an application directory. This module turns
a directory into an archive and an archive into an extracted tree in
the cache. It knows nothing about application names or the installed
index; cli.applications decides what those trees are.

Archives are copied into the cache and extracted there, because
containers mount the result and outlive the command that started them.

Which files an archive holds is cli.manifest's decision: an archive
holds exactly the files its application's manifest lists, and
write_archive checks that before returning.
"""

import hashlib
import shutil
import tarfile
import gzip

from pathlib import Path

from cli import manifest
from cli.config import APPLICATION_CONFIG_NAME
from cli.manifest import ARCHIVE_SUFFIXES
from cli.paths import (
    archives_dir,
    cache_dir_from_system_config,
    ensure_cache_layout,
    extracted_applications_dir,
)

def is_archive(target: str) -> bool:
    return target.endswith(ARCHIVE_SUFFIXES)


def archive_digest(archive: Path) -> str:
    """sha256 of an archive, read in chunks rather than in one piece."""
    digest = hashlib.sha256()

    with open(archive, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)

    return digest.hexdigest()


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
    members = manifest.application_files(source)

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

    expected = manifest.manifest_text(source)
    written = archive_manifest(archive)

    if written != expected:
        archive.unlink()
        raise ValueError(
            f"{archive}: the archive's files differ from {source}'s manifest; "
            "the archive was removed"
        )

    return len(members)


def archive_manifest(archive: Path) -> str:
    """The manifest of the application inside an archive, read in place.

    Computed from the members without extracting them, by the same
    rules as cli.manifest.manifest_text for a directory. An archive
    holding one top-level directory is read from inside it.
    """
    with tarfile.open(archive) as tar:
        files = [member for member in tar.getmembers() if member.isfile()]
        names = [member.name for member in files]

        prefix = ""
        if APPLICATION_CONFIG_NAME not in names:
            tops = {name.split("/", 1)[0] for name in names}
            if len(tops) == 1:
                prefix = tops.pop() + "/"

        lines = []

        for member in files:
            path = member.name.removeprefix(prefix)
            content = tar.extractfile(member)
            digest = hashlib.sha256()
            for chunk in iter(lambda: content.read(1 << 20), b""):
                digest.update(chunk)
            mode = manifest.file_mode(bool(member.mode & 0o100))
            lines.append((path.encode("utf-8"), manifest.format_line(mode, digest.hexdigest(), path)))

    return "".join(line for _, line in sorted(lines))


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

    The cache location comes from marigold-host.toml alone: the
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
