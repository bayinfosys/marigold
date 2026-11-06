"""marigold-registry.toml: a registry's identity.

The registry counterpart of marigold.toml. It sits at the root of a
repository of applications and declares the registry's title,
description and links, and optionally a site template and visitor text.
It is required: a registry always declares what it is. Every directory
under the root holding marigold.toml is published; this file does not
select applications.

Not named marigold.toml: registry discovery treats any directory holding
marigold.toml as an application, which would make the root one.
"""

import tomllib

from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from cli.application_config import REGISTRY_SCHEMES

REGISTRY_CONFIG_NAME = "marigold-registry.toml"

REGISTRY_CONFIG_EXAMPLE = (
    "[registry]\n"
    'title = "..."\n'
    'description = "..."'
)


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegistrySection(_Section):
    title: str
    description: str
    site: str | None = None
    front_page: str | None = None
    urls: dict[str, str] = {}

    @field_validator("title", "description")
    @classmethod
    def _not_blank(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value

    @field_validator("urls")
    @classmethod
    def _urls(cls, value):
        for key, url in value.items():
            if not url.startswith(REGISTRY_SCHEMES):
                raise ValueError(f"urls.{key}: '{url}' must be http:// or https://")
        return value


class RegistryConfig(_Section):
    registry: RegistrySection


def load_registry_config(path: Path) -> RegistryConfig:
    """Parse and validate marigold-registry.toml; errors name file and key."""
    if not path.is_file():
        raise FileNotFoundError(
            f"no {REGISTRY_CONFIG_NAME} in {path.parent}. A registry declares "
            f"itself there:\n\n{REGISTRY_CONFIG_EXAMPLE}"
        )

    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"cannot parse {path}: {e}") from e

    try:
        return RegistryConfig.model_validate(data)
    except ValidationError as e:
        lines = [
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in e.errors()
        ]
        raise ValueError(f"{path}:\n  " + "\n  ".join(lines)) from None
