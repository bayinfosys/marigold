"""Configuration: the host config and the application config, merged.

Two files, each with its own validated model:

    marigold-host.toml  how this machine runs the platform (marigold.cli.host_config)
    marigold.toml       what one application is and runs (marigold.cli.application_config)

The host sections are [platform], [storage], [database], [registry],
[network], [resources] and [models]. An application config that sets
one is rejected. Both files may set [environment]; the application's values
win per key.

Every other module reads configuration through these models, or through
the merged dictionary load_config() returns, which holds both models
dumped with their defaults. Nothing reads TOML or the environment for
settings anywhere else.

Nothing here exits: callers decide what a missing or malformed config
means for them.
"""

import tomllib

# PackageNotFoundError is importlib's term for a Python distribution
# package. It is unrelated to Marigold applications.
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from marigold.cli.application_config import ApplicationConfig, validate_application_config
from marigold.cli.host_config import HostConfig, host_config_path, load_host_config

APPLICATION_CONFIG_NAME = "marigold.toml"

# Host settings. An application config that sets one is rejected: the
# host decides how the platform runs, and an application adds services
# to it through [application].compose_files.
HOST_SECTIONS = tuple(name for name in HostConfig.model_fields if name != "environment")


def marigold_version() -> str:
    """The installed marigold version, which is also the default image tag."""
    try:
        return version("bayis-marigold")
    except PackageNotFoundError:
        return "0.0.0-dev"


def check_application_config(data: dict, path) -> dict:
    """Reject host sections in an application config."""
    host = [f"[{s}]" for s in HOST_SECTIONS if s in data]

    if host:
        raise ValueError(
            f"{path}: {', '.join(host)} must be set in marigold-host.toml, "
            "not in an application. An application adds platform services "
            "with [application].compose_files."
        )

    return data


def parse_application_config(text: str, source) -> ApplicationConfig:
    """Parse and validate marigold.toml content. source names it in errors."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"cannot parse {source}: {e}") from e

    check_application_config(data, source)
    return validate_application_config(data, source)


def load_application_config(path: Path) -> ApplicationConfig:
    """An application's marigold.toml, validated. A missing file is empty."""
    if not path.exists():
        return ApplicationConfig()

    return parse_application_config(path.read_text(encoding="utf-8"), path)


def load_application_toml(path: Path) -> dict:
    """An application's marigold.toml as a dict of the keys it sets."""
    return load_application_config(path).model_dump(exclude_unset=True)


def host_dict(host: HostConfig) -> dict:
    """The host config as plain values, defaults included."""
    return host.model_dump(mode="json")


def merge_config(host: dict, application: dict) -> dict:
    """Shallow-merge each top-level section; application values win per key.

    The sections only overlap in [environment], since an application may
    not set host sections.
    """
    merged: dict = {}

    for section in set(host) | set(application):
        host_section = host.get(section, {})
        app_section = application.get(section, {})

        if isinstance(host_section, dict) and isinstance(app_section, dict):
            merged[section] = {**host_section, **app_section}
        else:
            merged[section] = app_section if section in application else host_section

    return merged


def host_from_config(config: dict) -> HostConfig:
    """The HostConfig inside a merged config, with the merged [environment]."""
    data = {section: config[section] for section in HOST_SECTIONS if section in config}
    data["environment"] = config.get("environment", {})
    return HostConfig.model_validate(data)


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

    host = host_dict(load_host_config())
    application = load_application_toml(application_config_path)

    return merge_config(host, application)


def load_platform_config() -> dict:
    """The host config alone, as a merged config, for commands with no application."""
    return host_dict(load_host_config())


def host_keys_set(path: Path | None) -> dict[str, set[str]]:
    """The keys the host config file sets, per section, for provenance."""
    if path is None:
        return {}

    host = load_host_config(path)
    keys = {}

    for section in HostConfig.model_fields:
        value = getattr(host, section)
        if isinstance(value, dict):
            keys[section] = set(value)
        elif isinstance(value, list):
            keys[section] = {"entries"} if section in host.model_fields_set else set()
        else:
            keys[section] = set(value.model_fields_set)

    return keys


__all__ = [
    "APPLICATION_CONFIG_NAME",
    "HOST_SECTIONS",
    "HostConfig",
    "check_application_config",
    "host_config_path",
    "host_dict",
    "host_from_config",
    "host_keys_set",
    "load_application_config",
    "load_application_toml",
    "load_config",
    "load_host_config",
    "load_platform_config",
    "marigold_version",
    "merge_config",
    "parse_application_config",
    "setting",
]
