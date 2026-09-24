"""Configuration: two TOML layers, package over system.

A system-level config (config.toml in the current directory,
~/.marigold/config.toml, or $MARIGOLD_CONFIG) carries host defaults --
cache location, database URL, which compose files the platform runs. A
package-level marigold.toml in the package root declares what the
package is and what its application runs. Package values win per key;
anything neither sets falls back to a hardcoded default.

Sections follow the three nouns:

    [platform]     host: compose files, image tag
    [cache]        host: where the cache lives
    [database]     host: connection string
    [package]      the package: name, version, models_yaml, extra
                   compose files it needs
    [execution]    the application: name, image, command
    [environment]  variables forwarded to every service

[deployment] is the pre-0.7 name for the platform and package settings
and is still read, with a warning. It mixed the two layers, which is
why it went.

Nothing here touches the filesystem beyond reading those two files, and
nothing here exits: callers decide what a missing or malformed config
means for them.
"""

import logging
import os
import tomllib

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

logger = logging.getLogger("marigold.cli.config")

PACKAGE_CONFIG_NAME = "marigold.toml"
SYSTEM_CONFIG_NAME = "config.toml"
DEFAULT_SYSTEM_CONFIG_PATH = Path.home() / ".marigold" / "config.toml"

# (section, key) -> the pre-0.7 (section, key) it was read from.
# package.compose_files has no entry: under [deployment] that key was
# the platform's whole list, which is platform.compose_files now.
LEGACY_KEYS = {
    ("platform", "compose_files"): ("deployment", "compose_files"),
    ("platform", "tag"): ("deployment", "tag"),
    ("package", "models_yaml"): ("deployment", "models_yaml"),
}

_warned: set = set()


def package_version() -> str:
    """The installed marigold version, which is also the image tag."""
    try:
        return version("bayis-marigold")
    except PackageNotFoundError:
        return "0.0.0-dev"


def system_config_path() -> Path:
    """The system config file in use.

    $MARIGOLD_CONFIG wins and must exist; then config.toml in the
    current directory, which makes a checkout self-contained; then the
    home directory.
    """
    override = os.environ.get("MARIGOLD_CONFIG")

    if override:
        path = Path(override)
        if not path.exists():
            raise FileNotFoundError(
                f"MARIGOLD_CONFIG set to '{path}', but it doesn't exist"
            )
        return path

    cwd_config = Path(SYSTEM_CONFIG_NAME)

    if cwd_config.exists():
        return cwd_config

    return DEFAULT_SYSTEM_CONFIG_PATH


def load_toml(path: Path) -> dict:
    """Parse one TOML file. A missing file is an empty config."""
    if not path.exists():
        return {}

    with open(path, "rb") as f:
        try:
            return tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            logger.exception("cannot parse %s", path)
            raise ValueError(f"cannot parse {path}: {e}") from e


def merge_config(system: dict, package: dict) -> dict:
    """Shallow-merge each top-level section; package values win per key.

    [environment] merges the same way -- a package can set one variable
    without needing to repeat any others the system config already set.
    """
    merged: dict = {}

    for section in set(system) | set(package):
        sys_section = system.get(section, {})
        pkg_section = package.get(section, {})

        if isinstance(sys_section, dict) and isinstance(pkg_section, dict):
            merged[section] = {**sys_section, **pkg_section}
        else:
            merged[section] = pkg_section if section in package else sys_section

    return merged


def _warn_legacy(section: str, key: str, legacy: tuple) -> None:
    """Say once, per key, that a pre-0.7 section is being read."""
    if (section, key) in _warned:
        return

    _warned.add((section, key))
    logger.warning(
        "[%s].%s is the old name for [%s].%s and will stop being read; "
        "move it in your config",
        legacy[0], legacy[1], section, key,
    )


def setting(config: dict, section: str, key: str, default=None):
    """One value from a merged config, with the pre-0.7 fallback."""
    if key in config.get(section, {}):
        return config[section][key]

    legacy = LEGACY_KEYS.get((section, key))

    if legacy and legacy[1] in config.get(legacy[0], {}):
        _warn_legacy(section, key, legacy)
        return config[legacy[0]][legacy[1]]

    return default


def load_config(package_dir: Path) -> dict:
    """The merged config for one package."""
    package_config_path = package_dir / PACKAGE_CONFIG_NAME

    if not package_config_path.exists():
        raise FileNotFoundError(
            f"no {PACKAGE_CONFIG_NAME} found in {package_dir} "
            "-- doesn't look like a marigold package"
        )

    system_config = load_toml(system_config_path())
    package_config = load_toml(package_config_path)

    return merge_config(system_config, package_config)


def load_system_config() -> dict:
    """The system layer alone, for commands with no package in hand."""
    return load_toml(system_config_path())


def resolve_with_source(system: dict, package: dict, section: str, key: str, default):
    """Resolve one config value and say which layer set it.

    Mirrors setting() and merge_config's precedence: package beats
    system, current section beats the pre-0.7 one, and a hardcoded
    default is the floor. Returned separately rather than merged, so
    `config show` can report provenance -- the thing that makes a
    surprising value diagnosable.
    """
    legacy = LEGACY_KEYS.get((section, key))

    candidates = [(package, section, "package"), (system, section, "system")]

    if legacy:
        candidates += [
            (package, legacy[0], f"package [{legacy[0]}]"),
            (system, legacy[0], f"system [{legacy[0]}]"),
        ]

    for layer, layer_section, source in candidates:
        if key in layer.get(layer_section, {}):
            return layer[layer_section][key], source

    return default, "default"
