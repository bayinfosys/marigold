"""Packages: identity, archives, installation, resolution.

A package is a directory, or an archive that extracts to one,
containing marigold.toml, its models.yaml files, and its application
code. Resolution turns an installed name, a directory, an archive or a
namespaced reference into a root on local disk; everything downstream
sees a directory and cannot tell which route produced it.

Archives are copied into the cache and extracted there, because
containers mount the result and outlive the command that started them.
The cache container reads only the cache, so a package it must see has
to be installed; the executor mounts whatever root resolution produced,
which is what makes editing a package directory in place work.

The installed index is written here for now. It belongs with the cache
container eventually, for the same reason model registration does: it
is local state the platform reads, behind a container that owns that
write access.
"""

import hashlib
import json
import re
import shutil
import tarfile

from datetime import datetime, timezone
from pathlib import Path

from cli.config import PACKAGE_CONFIG_NAME, load_toml, setting
from cli.paths import (
    cache_dir_from_system_config,
    cache_paths,
    ensure_cache_layout,
    extracted_packages_dir,
)

# compose project and container names: lowercase, digits, hyphens.
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_NAME_SEPARATORS = re.compile(r"[^a-z0-9]+")

PACKAGE_ARCHIVE_SUFFIXES = (".tar.gz", ".tgz", ".marigold")

INSTALLED_INDEX_NAME = "installed.json"

# Never packaged: caches, VCS metadata, virtualenvs, build output.
ARCHIVE_EXCLUDED_NAMES = {
    ".git", ".hg", ".svn", "__pycache__", ".venv", "venv", "node_modules",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".DS_Store", "dist", "build",
}
ARCHIVE_EXCLUDED_SUFFIXES = (".pyc", ".pyo") + PACKAGE_ARCHIVE_SUFFIXES


# ---------------------------------------------------------------------------
# identity
# ---------------------------------------------------------------------------

def package_identity(package_dir: Path, config: dict) -> tuple[str, str]:
    """(name, version) for a package, from [package] or the directory.

    The version is a label on the archive, not something Marigold
    compares or orders: two versions of one package are two installed
    packages, distinguished by name where they need to coexist.
    """
    section = config.get("package", {})
    name = str(section.get("name") or package_dir.name).lower()

    if not NAME_RE.match(name):
        raise ValueError(
            f"invalid package name '{name}': lowercase letters, digits and "
            f"hyphens only. Set [package].name in {PACKAGE_CONFIG_NAME}."
        )

    return name, str(section.get("version", "0"))


def application_name(package_dir: Path, config: dict) -> str:
    """The name this package's application containers run under.

    [execution].name, then [package].name, then the directory name.
    Declaring it lets one package run under two application names, and
    stops an archive extracting to a content-addressed directory from
    moving an application's containers out from under it.

    A derived name is coerced to the character set compose accepts
    (underscores and dots become hyphens), since a directory name is
    not written with compose in mind. A declared name is taken as given
    and rejected if it does not fit, because a silent rewrite of
    something the package author typed is worse than an error.
    """
    declared = (
        config.get("execution", {}).get("name")
        or config.get("package", {}).get("name")
    )

    if declared:
        name = str(declared).lower()
        if not NAME_RE.match(name):
            raise ValueError(
                f"invalid application name '{declared}': lowercase letters, "
                "digits and hyphens only."
            )
        return name

    name = _NAME_SEPARATORS.sub("-", package_dir.name.lower()).strip("-")

    if not name or not NAME_RE.match(name):
        raise ValueError(
            f"cannot derive an application name from directory "
            f"'{package_dir.name}'. Set [execution].name in "
            f"{PACKAGE_CONFIG_NAME}."
        )

    return name


def models_yaml_paths(package_dir: Path, config: dict) -> list[Path]:
    """The models.yaml files a package declares, as host paths."""
    names = setting(config, "package", "models_yaml", ["models.yaml"])
    paths = [package_dir / name for name in names]
    missing = [p for p in paths if not p.exists()]

    if missing:
        raise FileNotFoundError(
            "declared models.yaml not found: " + ", ".join(str(p) for p in missing)
        )

    return paths


def package_models(package_dir: Path, config: dict) -> list:
    """The catalogue items a package declares.

    Parsed in-process, which is what `cache validate` is: no torch, no
    network, no database at import time in models.catalogue, checked
    directly before this was written.
    """
    from models.catalogue import load_catalogue_from_yaml

    return load_catalogue_from_yaml(
        [str(p) for p in models_yaml_paths(package_dir, config)]
    )


# ---------------------------------------------------------------------------
# installed index
# ---------------------------------------------------------------------------

def installed_index_path() -> Path:
    return cache_paths(cache_dir_from_system_config())["packages"] / INSTALLED_INDEX_NAME


def load_installed() -> dict:
    """The installed package index: name -> record."""
    path = installed_index_path()

    if not path.exists():
        return {}

    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise ValueError(f"cannot parse {path}: {e}") from e


def save_installed(index: dict) -> None:
    ensure_cache_layout(cache_dir_from_system_config())
    path = installed_index_path()

    staging = path.with_suffix(".partial")
    staging.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n")
    staging.replace(path)


# ---------------------------------------------------------------------------
# archives
# ---------------------------------------------------------------------------

def archive_digest(archive: Path) -> str:
    """sha256 of an archive, read in chunks rather than in one piece."""
    digest = hashlib.sha256()

    with open(archive, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)

    return digest.hexdigest()


def is_archive(target: str) -> bool:
    return target.endswith(PACKAGE_ARCHIVE_SUFFIXES)


def _archive_members(source: Path) -> list[Path]:
    """Files to package, sorted, excluding caches and build output."""
    members = []

    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)

        if any(part in ARCHIVE_EXCLUDED_NAMES for part in relative.parts):
            continue
        if path.name.endswith(ARCHIVE_EXCLUDED_SUFFIXES):
            continue
        if not path.is_file():
            continue

        members.append(path)

    return members


def _archive_member_filter(info: tarfile.TarInfo) -> tarfile.TarInfo:
    """Strip host identity from archive members.

    Ownership and permission bits beyond the read/execute distinction
    are the extracting host's business, and a package carrying the
    builder's uid extracts differently for everyone else.
    """
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    info.mode = 0o755 if info.mode & 0o100 else 0o644
    return info


def create_archive(source: Path, output: Path) -> tuple[Path, int]:
    """Build a package archive from a package directory.

    output is a directory, or a filename when it ends in an archive
    suffix. Returns (archive path, file count).
    """
    config_path = source / PACKAGE_CONFIG_NAME

    if not config_path.exists():
        raise FileNotFoundError(f"no {PACKAGE_CONFIG_NAME} in {source}")

    config = load_toml(config_path)
    name, package_ver = package_identity(source, config)

    if is_archive(output.name):
        archive = output
        archive.parent.mkdir(parents=True, exist_ok=True)
    else:
        output.mkdir(parents=True, exist_ok=True)
        archive = output / f"{name}-{package_ver}.tar.gz"

    members = _archive_members(source)

    with tarfile.open(archive, "w:gz") as tar:
        for path in members:
            tar.add(
                path,
                arcname=str(path.relative_to(source)),
                filter=_archive_member_filter,
            )

    return archive, len(members)


def _package_root(extracted: Path) -> Path:
    """The package root inside an extracted archive.

    Archives are written both ways: files at the top level, or one
    directory containing them (pkg-1.0/marigold.toml). Both resolve
    here, so neither is a packaging error.
    """
    if (extracted / PACKAGE_CONFIG_NAME).exists():
        return extracted

    children = [c for c in extracted.iterdir() if not c.name.startswith(".")]

    if len(children) == 1 and children[0].is_dir():
        if (children[0] / PACKAGE_CONFIG_NAME).exists():
            return children[0]

    raise ValueError(
        f"no {PACKAGE_CONFIG_NAME} at the root of the extracted package "
        f"({extracted})"
    )


def extract_archive(archive: Path) -> tuple[Path, Path, str]:
    """Copy a package archive into the cache and extract it there.

    Returns (extraction directory, package root, digest). The two paths
    differ when the archive holds one top-level directory; uninstall
    removes the extraction directory, so both are recorded.

    Content-addressed: the same archive always resolves to the same
    root, is extracted once, and stop/status/logs reach the tree start
    used.

    The cache location comes from the system config alone: the package
    config is inside the archive and cannot be read before it exists.
    """
    cache_dir = cache_dir_from_system_config()
    ensure_cache_layout(cache_dir)

    digest = archive_digest(archive)

    kept = cache_paths(cache_dir)["packages"] / f"{digest}.tar.gz"
    if not kept.exists():
        shutil.copy2(archive, kept)

    target = extracted_packages_dir(cache_dir) / digest[:16]

    if target.exists():
        return target, _package_root(target), digest

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

    return target, _package_root(target), digest


# ---------------------------------------------------------------------------
# install
# ---------------------------------------------------------------------------

def install_archive(archive: Path) -> tuple[str, str, Path, str, dict | None]:
    """Install a package archive.

    Returns (name, version, root, digest, previous record or None).
    """
    extracted, root, digest = extract_archive(archive)

    config = load_toml(root / PACKAGE_CONFIG_NAME)
    name, package_ver = package_identity(root, config)

    index = load_installed()
    previous = index.get(name)

    index[name] = {
        "version": package_ver,
        "digest": digest,
        "root": str(root),
        "extracted": str(extracted),
        "archive": str(
            cache_paths(cache_dir_from_system_config())["packages"] / f"{digest}.tar.gz"
        ),
        "installed_at": datetime.now(timezone.utc).isoformat(),
    }
    save_installed(index)

    return name, package_ver, root, digest, previous


def uninstall(name: str) -> dict:
    """Remove a package from the installed index, returning its record.

    The extracted tree goes with it unless another installed package
    shares the digest. The archive stays in the cache: it is
    content-addressed, and keeping it makes a reinstall free.
    """
    index = load_installed()
    record = index.pop(name, None)

    if record is None:
        raise FileNotFoundError(f"'{name}' is not installed")

    save_installed(index)

    if not any(other["digest"] == record["digest"] for other in index.values()):
        shutil.rmtree(record.get("extracted", record["root"]), ignore_errors=True)

    return record


# ---------------------------------------------------------------------------
# resolution
# ---------------------------------------------------------------------------

def resolve_target(target: str) -> Path:
    """Resolve a target to a package root on local disk.

    target is the name of an installed package, a directory, a package
    archive (.tar.gz/.tgz/.marigold), or a namespaced package reference
    '<host>.<package_name>' (e.g. 'bayinfosys.simple-rag').

    The installed index is checked first, so a directory sitting in the
    working directory does not shadow an installed package of the same
    name. A path is still a path: './platform-test' resolves to the
    directory.

    Namespaced references are meant to resolve by: checking whether the
    package is already installed, then querying each repository in the
    system config's [repositories] list, in order, until one has it. A
    fetched archive then takes the archive path above.

    STUB: repository resolution is not implemented -- no manifest
    format, no repository protocol, no signing. See PACKAGES.md.
    """
    installed = load_installed().get(target)

    if installed is not None:
        root = Path(installed["root"])
        if not (root / PACKAGE_CONFIG_NAME).exists():
            raise FileNotFoundError(
                f"'{target}' is installed but its files are gone ({root}). "
                f"Reinstall it, or run: marigold package uninstall {target}"
            )
        return root

    path = Path(target)

    if path.is_dir():
        return path.resolve()

    if path.is_file():
        if is_archive(target):
            _, root, _ = extract_archive(path.resolve())
            return root
        raise ValueError(
            f"'{target}' is not a package archive "
            f"({', '.join(PACKAGE_ARCHIVE_SUFFIXES)})"
        )

    if "." in target and not path.suffix:
        raise NotImplementedError(
            f"'{target}' looks like a namespaced package reference "
            "(<host>.<package_name>), but package repository "
            "resolution isn't implemented yet. Pass a filesystem "
            "path instead."
        )

    raise FileNotFoundError(f"package not found: {target}")
