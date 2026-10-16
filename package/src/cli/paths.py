"""The cache layout: one definition of where things live on disk.

Compose receives these paths as environment variables rather than
composing them itself, so the host and the containers cannot disagree.
"""

from pathlib import Path

from cli.config import load_system_config

DEFAULT_CACHE_DIR = Path.home() / ".marigold" / "cache"

CACHE_SUBDIRS = {
    "models":       "data/models",
    "tmp":          "data/tmp",
    "outputs":      "data/outputs",
    "applications": "data/applications",
}

# Inside the applications directory, anything that is not one
# application's own directory starts with an underscore or contains a
# dot. Application names are [a-z0-9-] only, so neither can collide.
ARCHIVES_SUBDIR = "_archives"           # archives as installed, by digest
EXTRACTED_SUBDIR = "_src"               # extracted application trees
INSTALLED_INDEX_NAME = "installed.json"

# Where the applications directory is mounted in the cache container,
# which is how it reads an installed application's models.yaml.
CONTAINER_APPLICATIONS_DIR = "/applications"


class CacheNotWritable(Exception):
    """The cache layout is missing and cannot be created as this user."""


def cache_paths(cache_dir: Path) -> dict[str, Path]:
    """Absolute host paths for everything under the cache root.

    models       -- downloaded weights, the model cache proper
    tmp          -- worker offload space
    outputs      -- inference outputs written by the worker
    applications -- installed applications: the index, the archives they
                    were installed from, the extracted trees and each
                    application's own outputs
    """
    return {name: cache_dir / rel for name, rel in CACHE_SUBDIRS.items()}


def archives_dir(cache_dir: Path) -> Path:
    return cache_paths(cache_dir)["applications"] / ARCHIVES_SUBDIR


def extracted_applications_dir(cache_dir: Path) -> Path:
    return cache_paths(cache_dir)["applications"] / EXTRACTED_SUBDIR


def installed_index_path(cache_dir: Path) -> Path:
    return cache_paths(cache_dir)["applications"] / INSTALLED_INDEX_NAME


def cache_dir_from_config(config: dict) -> Path:
    """The cache root from a merged config.

    Cache location is a host concern, so this reads whatever the config
    resolved to, or a last resort if neither layer set one at all (e.g.
    no system config written yet).
    """
    return Path(config.get("cache", {}).get("dir", str(DEFAULT_CACHE_DIR)))


def cache_dir_from_system_config() -> Path:
    """The cache root for commands with no application in hand."""
    return cache_dir_from_config(load_system_config())


def container_path(path: Path, cache_dir: Path) -> str:
    """A host path under the applications directory, as the cache
    container sees it.

    Raises if the path is outside: the cache container mounts the cache
    and nothing else, so an application it must read has to be installed.
    """
    applications = cache_paths(cache_dir)["applications"]

    try:
        relative = Path(path).relative_to(applications)
    except ValueError as e:
        raise ValueError(
            f"{path} is not inside the cache ({applications}), so the cache "
            "container cannot read it. Install the application first:\n"
            f"  marigold application create {path} -o /tmp\n"
            "  marigold application install /tmp/<name>-<version>.tar.gz"
        ) from e

    return f"{CONTAINER_APPLICATIONS_DIR}/{relative}"


def ensure_cache_layout(cache_dir: Path) -> dict[str, Path]:
    """Create the cache layout, returning the paths.

    Called before anything the CLI writes from the host. Idempotent.
    """
    paths = cache_paths(cache_dir)
    extra = [archives_dir(cache_dir), extracted_applications_dir(cache_dir)]

    for path in list(paths.values()) + extra:
        if path.exists():
            continue

        try:
            path.mkdir(parents=True, exist_ok=True)
        except PermissionError as e:
            raise CacheNotWritable(
                f"cannot create {path}.\n"
                f"  sudo mkdir -p {path}\n"
                f"  sudo chown -R $(id -u):$(id -g) {path}"
            ) from e

    return paths
