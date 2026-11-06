"""marigold.toml as a validated object.

An application config has three sections:

    [application]  identity and contents: name, version, description,
                   models_yaml, compose_files, requires
    [execution]    the application's containers: name, image, command
    [environment]  variables forwarded to every service

Unknown sections and unknown keys are errors, so a misspelt key fails
when the config is read. Host sections and earlier section names are
rejected before validation by cli.config, with messages naming the
change.

Names are in PEP 503 normal form: lowercase letters and digits with
single hyphens between them. A declared name must already be in that
form. canonical_name() is for lookups, where a user typing
'platform_model_test' means 'platform-model-test'.

Versions are PEP 440, stored normalised ('1.0-alpha1' becomes '1.0a1').
"""

import re

from packaging.requirements import InvalidRequirement, Requirement
from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_SEPARATORS = re.compile(r"[-_.]+")

REGISTRY_SCHEMES = ("http://", "https://")


def canonical_name(name: str) -> str:
    """PEP 503 normal form: lowercase; runs of '-', '_', '.' become one '-'."""
    return _SEPARATORS.sub("-", str(name)).lower().strip("-")


def check_name(name: str) -> str:
    """A declared name, unchanged, or an error giving its normal form."""
    name = str(name)

    if NAME_RE.match(name):
        return name

    normal = canonical_name(name)
    hint = f"; write it as '{normal}'" if NAME_RE.match(normal) else ""

    raise ValueError(
        f"invalid name '{name}': lowercase letters and digits separated "
        f"by single hyphens{hint}"
    )


def parse_requirement(text: str) -> tuple[str | None, Requirement]:
    """Split a requires entry into (registry base URL or None, requirement).

    'platform-model-test>=0.1' resolves through the configured
    registries. 'https://host/path/summariser==0.2.0' names the registry
    at 'https://host/path/'. Names contain no '/', so splitting at the
    last '/' is unambiguous.
    """
    text = str(text).strip()
    base = None

    if "://" in text:
        base, _, text = text.rpartition("/")
        base += "/"
        if not base.startswith(REGISTRY_SCHEMES):
            raise ValueError(f"registry URL '{base}' must be http:// or https://")

    try:
        requirement = Requirement(text)
    except InvalidRequirement as e:
        raise ValueError(f"invalid requirement '{text}': {e}") from None

    if requirement.url or requirement.extras or requirement.marker:
        raise ValueError(
            f"invalid requirement '{text}': a name and version specifiers "
            "only, with no extras, markers or direct URLs"
        )

    check_name(requirement.name)
    return base, requirement


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ApplicationSection(_Section):
    name: str | None = None
    version: str | None = None
    description: str | None = None
    models_yaml: list[str] = ["models.yaml"]
    compose_files: list[str] = []
    requires: list[str] = []
    urls: dict[str, str] = {}

    @field_validator("name", mode="before")
    @classmethod
    def _name(cls, value):
        return None if value is None else check_name(value)

    @field_validator("version", mode="before")
    @classmethod
    def _version(cls, value):
        if value is None:
            return None

        # TOML reads 1.10 as the float 1.1: a version must be a string.
        if not isinstance(value, str):
            raise ValueError(f"version {value!r} must be a quoted string")

        try:
            return str(Version(value))
        except InvalidVersion:
            raise ValueError(f"'{value}' is not a PEP 440 version") from None

    @field_validator("requires")
    @classmethod
    def _requires(cls, value):
        for entry in value:
            parse_requirement(entry)
        return [entry.strip() for entry in value]

    @field_validator("urls")
    @classmethod
    def _urls(cls, value):
        for key, url in value.items():
            if not url.startswith(REGISTRY_SCHEMES):
                raise ValueError(f"urls.{key}: '{url}' must be http:// or https://")
        return value


class ExecutionSection(_Section):
    name: str | None = None
    image: str | None = None
    command: list[str] | str | None = None

    @field_validator("name", mode="before")
    @classmethod
    def _name(cls, value):
        return None if value is None else check_name(value)


class ApplicationConfig(_Section):
    application: ApplicationSection = Field(default_factory=ApplicationSection)
    execution: ExecutionSection = Field(default_factory=ExecutionSection)
    environment: dict[str, str | int | float | bool] = {}


def validate_application_config(data: dict, source) -> ApplicationConfig:
    """Validate a parsed marigold.toml; errors name the file and the key."""
    try:
        return ApplicationConfig.model_validate(data)
    except ValidationError as e:
        lines = [
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in e.errors()
        ]
        raise ValueError(f"{source}:\n  " + "\n  ".join(lines)) from None
