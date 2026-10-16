"""Applications: identity, declared models, installation, resolution.

An application is a directory, or an archive that extracts to one,
containing marigold.toml, its models.yaml files and its code.
Resolution turns an installed name, a directory, an archive or a
namespaced reference into a root on local disk; everything downstream
sees a directory and cannot tell which route produced it.

The cache container reads only the cache, so an application it must
see has to be installed; the executor mounts whatever root resolution
produced, which is what makes editing an application directory in
place work.

The installed index is written here for now. It belongs with the cache
container eventually, for the same reason model registration does: it
is local state the platform reads, behind a container that owns that
write access.
"""

import json
import re
import shutil

from datetime import datetime, timezone
from pathlib import Path

from cli import archives
from cli.config import APPLICATION_CONFIG_NAME, load_application_toml, setting
from cli.paths import (
    cache_dir_from_system_config,
    ensure_cache_layout,
    installed_index_path as _installed_index_path,
)

# compose project and container names: lowercase, digits, hyphens.
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_NAME_SEPARATORS = re.compile(r"[^a-z0-9]+")


# ---------------------------------------------------------------------------
# identity
# ---------------------------------------------------------------------------

def application_identity(
    application_dir: Path,
    config: dict,
    require_declared: bool = False,
) -> tuple[str, str]:
    """(name, version) for an application.

    From [application].name and [application].version. Running straight
    from a directory may leave them out: the directory name and version
    "0" stand in. Building or installing an archive passes
    require_declared, because an extracted archive sits in a
    content-addressed directory whose name says nothing about the
    application, so the archive must carry its identity itself.

    The version is a label on the archive, not something Marigold
    compares or orders.
    """
    section = config.get("application", {})
    declared_name = section.get("name")
    declared_version = section.get("version")

    if require_declared:
        missing = [
            key for key, value in (("name", declared_name), ("version", declared_version))
            if not value
        ]
        if missing:
            raise ValueError(
                f"{application_dir / APPLICATION_CONFIG_NAME}: "
                f"[application] needs {' and '.join(missing)} to build or "
                "install an archive"
            )

    name = str(declared_name or application_dir.name).lower()

    if not NAME_RE.match(name):
        raise ValueError(
            f"invalid application name '{name}': lowercase letters, digits "
            f"and hyphens only. Set [application].name in "
            f"{APPLICATION_CONFIG_NAME}."
        )

    return name, str(declared_version or "0")


def application_name(application_dir: Path, config: dict) -> str:
    """The name this application's containers run under.

    [execution].name, then [application].name, then the directory name.
    Declaring it lets one application run under two names, and stops an
    archive extracting to a content-addressed directory from moving an
    application's containers out from under it.

    A derived name is coerced to the character set compose accepts
    (underscores and dots become hyphens), since a directory name is
    not written with compose in mind. A declared name is taken as given
    and rejected if it does not fit, because a silent rewrite of
    something the author typed is worse than an error.
    """
    declared = (
        config.get("execution", {}).get("name")
        or config.get("application", {}).get("name")
    )

    if declared:
        name = str(declared).lower()
        if not NAME_RE.match(name):
            raise ValueError(
                f"invalid application name '{declared}': lowercase letters, "
                "digits and hyphens only."
            )
        return name

    name = _NAME_SEPARATORS.sub("-", application_dir.name.lower()).strip("-")

    if not name or not NAME_RE.match(name):
        raise ValueError(
            f"cannot derive an application name from directory "
            f"'{application_dir.name}'. Set [execution].name in "
            f"{APPLICATION_CONFIG_NAME}."
        )

    return name


def models_yaml_paths(application_dir: Path, config: dict) -> list[Path]:
    """The models.yaml files an application declares, as host paths."""
    names = setting(config, "application", "models_yaml", ["models.yaml"])
    paths = [application_dir / name for name in names]
    missing = [p for p in paths if not p.exists()]

    if missing:
        raise FileNotFoundError(
            "declared models.yaml not found: " + ", ".join(str(p) for p in missing)
        )

    return paths


def application_models(application_dir: Path, config: dict) -> list:
    """The catalogue items an application declares.

    Parsed in-process, which is what `cache validate` is: no torch, no
    network, no database at import time in models.catalogue, checked
    directly before this was written.
    """
    from models.catalogue import load_catalogue_from_yaml

    return load_catalogue_from_yaml(
        [str(p) for p in models_yaml_paths(application_dir, config)]
    )


# ---------------------------------------------------------------------------
# installed index
# ---------------------------------------------------------------------------

def installed_index_path() -> Path:
    return _installed_index_path(cache_dir_from_system_config())


def load_installed() -> dict:
    """The installed application index: name -> record."""
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
# build and install
# ---------------------------------------------------------------------------

def build_archive(source: Path, output: Path) -> tuple[Path, int]:
    """Build an application archive from an application directory.

    output is a directory, or a filename when it ends in an archive
    suffix. Returns (archive path, file count).
    """
    config_path = source / APPLICATION_CONFIG_NAME

    if not config_path.exists():
        raise FileNotFoundError(f"no {APPLICATION_CONFIG_NAME} in {source}")

    name, version = application_identity(
        source, load_application_toml(config_path), require_declared=True
    )

    if archives.is_archive(output.name):
        archive = output
    else:
        archive = output / f"{name}-{version}.tar.gz"

    return archive, archives.write_archive(source, archive)


def install(archive: Path) -> tuple[str, str, Path, str, dict | None]:
    """Install an application archive.

    Returns (name, version, root, digest, previous record or None).
    """
    extracted, root, digest, kept = archives.extract_archive(archive)

    config = load_application_toml(root / APPLICATION_CONFIG_NAME)
    name, version = application_identity(root, config, require_declared=True)

    index = load_installed()
    previous = index.get(name)

    index[name] = {
        "version": version,
        "digest": digest,
        "root": str(root),
        "extracted": str(extracted),
        "archive": str(kept),
        "installed_at": datetime.now(timezone.utc).isoformat(),
    }
    save_installed(index)

    return name, version, root, digest, previous


def uninstall(name: str) -> dict:
    """Remove an application from the installed index, returning its record.

    The extracted tree goes with it unless another installed application
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
    """Resolve a target to an application root on local disk.

    target is the name of an installed application, a directory, an
    application archive (.tar.gz/.tgz/.marigold), or a namespaced
    reference '<namespace>.<name>' (e.g. 'bayinfosys.simple-rag').

    The installed index is checked first, so a directory sitting in the
    working directory does not shadow an installed application of the
    same name. A path is still a path: './platform-test' resolves to the
    directory.

    Namespaced references will resolve through the remotes in the
    system config, fetching an archive that then takes the archive path
    above. Not implemented: see TODO.md, package distribution.
    """
    installed = load_installed().get(target)

    if installed is not None:
        root = Path(installed["root"])
        if not (root / APPLICATION_CONFIG_NAME).exists():
            raise FileNotFoundError(
                f"'{target}' is installed but its files are gone ({root}). "
                f"Reinstall it, or run: marigold application uninstall {target}"
            )
        return root

    path = Path(target)

    if path.is_dir():
        return path.resolve()

    if path.is_file():
        if archives.is_archive(target):
            _, root, _, _ = archives.extract_archive(path.resolve())
            return root
        raise ValueError(
            f"'{target}' is not an application archive "
            f"({', '.join(archives.ARCHIVE_SUFFIXES)})"
        )

    if "." in target and not path.suffix:
        raise NotImplementedError(
            f"'{target}' looks like a namespaced application reference "
            "(<namespace>.<name>), but fetching from remotes isn't "
            "implemented yet. Pass a filesystem path instead."
        )

    raise FileNotFoundError(f"application not found: {target}")
