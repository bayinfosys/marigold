"""Configuration: two TOML layers; application values win over system values.

A system-level config (config.toml in the current directory,
~/.marigold/config.toml, or $MARIGOLD_CONFIG) carries host defaults --
cache location, database URL, which compose files the platform runs. An
application-level marigold.toml in the application root declares what
the application is and what it runs. Application values win per key;
anything neither sets falls back to a hardcoded default.

Sections:

    [platform]     host: compose files, image tag
    [cache]        host: where the cache lives
    [database]     host: connection string
    [application]  the application: name, version, models_yaml, extra
                   compose files it needs
    [execution]    the application's containers: name, image, command
    [environment]  variables forwarded to every service

[package] and [deployment] are earlier section names. An application
config that still uses either is rejected with a message naming the
change.

Nothing here touches the filesystem beyond reading those two files, and
nothing here exits: callers decide what a missing or malformed config
means for them.
"""

import logging
import os
import tomllib

# PackageNotFoundError is importlib's term for a Python distribution
# package. It is unrelated to Marigold applications.
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

logger = logging.getLogger("marigold.cli.config")

APPLICATION_CONFIG_NAME = "marigold.toml"
SYSTEM_CONFIG_NAME = "config.toml"
DEFAULT_SYSTEM_CONFIG_PATH = Path.home() / ".marigold" / "config.toml"

# Earlier section names in an application config, and what to do instead.
RENAMED_SECTIONS = {
    "package": "rename [package] to [application]",
    "deployment": (
        "[deployment] is no longer read: host settings go in [platform] "
        "in the system config, application settings in [application]"
    ),
}


def marigold_version() -> str:
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


# Host settings. An application config that sets them is rejected: the
# host decides how the platform runs, and an application adds services
# to it through [application].compose_files.
HOST_SECTIONS = ("platform", "cache", "database")


def check_application_config(data: dict, path: Path) -> dict:
    """Reject earlier section names and host settings in an application config."""
    for section, message in RENAMED_SECTIONS.items():
        if section in data:
            raise ValueError(f"{path}: {message}")

    host = [f"[{s}]" for s in HOST_SECTIONS if s in data]

    if host:
        raise ValueError(
            f"{path}: {', '.join(host)} must be set in the system "
            "config.toml, not in an application. An application adds "
            "platform services with [application].compose_files."
        )

    return data


def load_application_toml(path: Path) -> dict:
    """Parse an application's marigold.toml and check its sections."""
    return check_application_config(load_toml(path), path)


def merge_config(system: dict, application: dict) -> dict:
    """Shallow-merge each top-level section; application values win per key.

    [environment] merges the same way -- an application can set one
    variable without repeating any others the system config already set.
    """
    merged: dict = {}

    for section in set(system) | set(application):
        sys_section = system.get(section, {})
        app_section = application.get(section, {})

        if isinstance(sys_section, dict) and isinstance(app_section, dict):
            merged[section] = {**sys_section, **app_section}
        else:
            merged[section] = app_section if section in application else sys_section

    return merged


def setting(config: dict, section: str, key: str, default=None):
    """One value from a merged config, or the default."""
    return config.get(section, {}).get(key, default)


def load_config(application_dir: Path) -> dict:
    """The merged config for one application."""
    application_config_path = application_dir / APPLICATION_CONFIG_NAME

    if not application_config_path.exists():
        raise FileNotFoundError(
            f"no {APPLICATION_CONFIG_NAME} found in {application_dir} "
            "-- doesn't look like a marigold application"
        )

    system_config = load_toml(system_config_path())
    application_config = load_application_toml(application_config_path)

    return merge_config(system_config, application_config)


def load_system_config() -> dict:
    """The system layer alone, for commands with no application in hand."""
    return load_toml(system_config_path())


def resolve_with_source(system: dict, application: dict, section: str, key: str, default):
    """Resolve one config value and say which layer set it.

    Mirrors merge_config's precedence: application beats system, and a
    hardcoded default is the floor. Returned separately rather than
    merged, so `config show` can report provenance -- the thing that
    makes a surprising value diagnosable.
    """
    for layer, source in ((application, "application"), (system, "system")):
        if key in layer.get(section, {}):
            return layer[section][key], source

    return default, "default"
