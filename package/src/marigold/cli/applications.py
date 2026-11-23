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

from marigold.cli import archives, manifest
from marigold.cli.config import APPLICATION_CONFIG_NAME, load_application_toml, setting
from marigold.cli.paths import (
    cache_dir_from_system_config,
    ensure_cache_layout,
    installed_index_path as _installed_index_path,
)
from marigold.cli.application_config import NAME_RE

_NAME_SEPARATORS = re.compile(r"[^a-z0-9]+")

# ---------------------------------------------------------------------------
# identity
# ---------------------------------------------------------------------------

LOCAL_VERSION = "local"


def declared_name(
    application_dir: Path,
    config: dict,
    require_declared: bool = False,
) -> str:
    """An application's name: [application].name.

    Running straight from a directory may leave it out, and the
    directory name stands in. Building or installing an archive passes
    require_declared, because an extracted archive sits in a
    content-addressed directory whose name says nothing about the
    application, so the archive must carry its name itself.

    Applications carry no version. A version is the registry's tag,
    given to the build that publishes it; anything built or installed
    outside a registry is LOCAL_VERSION.
    """
    name = config.get("application", {}).get("name")

    if require_declared and not name:
        raise ValueError(
            f"{application_dir / APPLICATION_CONFIG_NAME}: [application] "
            "needs name to build or install an archive"
        )

    name = str(name or application_dir.name).lower()

    if not NAME_RE.match(name):
        raise ValueError(
            f"invalid application name '{name}': lowercase letters, digits "
            f"and hyphens only. Set [application].name in "
            f"{APPLICATION_CONFIG_NAME}."
        )

    return name


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
    network, no database at import time in shared.catalogue, checked
    directly before this was written.
    """
    from marigold.shared.catalogue import load_catalogue_from_yaml

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

def build_archive(source: Path, output: Path, version: str = LOCAL_VERSION) -> tuple[Path, int, str]:
    """Build an application archive from an application directory.

    output is a directory, or a filename when it ends in an archive
    suffix; a directory gets <name>-<version>.tar.gz. Returns (archive
    path, file count, manifest digest).
    """
    config_path = source / APPLICATION_CONFIG_NAME

    if not config_path.exists():
        raise FileNotFoundError(f"no {APPLICATION_CONFIG_NAME} in {source}")

    name = declared_name(source, load_application_toml(config_path), require_declared=True)

    if archives.is_archive(output.name):
        archive = output
    else:
        archive = output / f"{name}-{version}.tar.gz"

    count = archives.write_archive(source, archive)
    _, digest = manifest.application_manifest(source)

    return archive, count, digest


def install(
    archive: Path,
    version: str = LOCAL_VERSION,
    expected_manifest: str | None = None,
    registry: str | None = None,
) -> tuple[str, Path, dict, dict | None]:
    """Install an application archive.

    version is the registry tag it was published under, or
    LOCAL_VERSION. expected_manifest, when given, is the digest the
    registry's index records; the installed files must match it.
    registry is the registry it came from, recorded for list.

    Returns (name, root, record, previous record or None).
    """
    extracted, root, digest, kept = archives.extract_archive(archive)
    _, manifest_digest = manifest.application_manifest(root)

    if expected_manifest is not None and manifest_digest != expected_manifest:
        raise ValueError(
            f"{archive}: files give digest {manifest.short(manifest_digest)}, "
            f"the index records {manifest.short(expected_manifest)}"
        )

    config = load_application_toml(root / APPLICATION_CONFIG_NAME)
    name = declared_name(root, config, require_declared=True)

    index = load_installed()
    previous = index.get(name)

    index[name] = {
        "version": version,
        "registry": registry,
        "manifest": manifest_digest,
        "digest": digest,
        "root": str(root),
        "extracted": str(extracted),
        "archive": str(kept),
        "installed_at": datetime.now(timezone.utc).isoformat(),
    }
    save_installed(index)

    return name, root, index[name], previous


def verify(name: str) -> tuple[dict, str]:
    """(installed record, digest of the files now) for one application."""
    record = load_installed().get(name)

    if record is None:
        raise FileNotFoundError(f"'{name}' is not installed")

    _, digest = manifest.application_manifest(Path(record["root"]))
    return record, digest


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
    host config, fetching an archive that then takes the archive path
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
