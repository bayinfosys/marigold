"""Model settings: how a model is loaded and run, by name and value.

A setting's name is its environment variable in lower case:
load_in_4bit is LOAD_IN_4BIT. The four settings the loaders read are
typed. Handlers read further settings, such as num_steps, which are
allowed as extra keys holding a string, a number or a boolean.

A models.yaml entry declares its settings under `settings:`, and the
host config's [models] section sets them for every model, by model type
and by model name. resolve_settings decides each setting's value at a
load; the worker and the cache container apply the result to the
process environment through shared.db_models.set_model_config_env.

This module imports only pydantic and shared.enums, so the CLI can
import it.
"""

import json
import os
import re

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shared.enums import ModelType

# The environment variable the CLI writes [models] to, as JSON.
HOST_SETTINGS_ENV = "MARIGOLD_MODEL_SETTINGS"

# The environment variable in lower case.
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class ModelSettings(BaseModel):
    """Settings for loading and running one model. Unset means not set."""

    model_config = ConfigDict(extra="allow")

    __pydantic_extra__: dict[str, str | int | float | bool]

    load_in_4bit: bool | None = Field(
        default=None,
        description="Quantise the weights to 4-bit as they load (bitsandbytes). Needs a GPU.",
    )
    use_fast: bool | None = Field(
        default=None,
        description="Load the fast tokenizer.",
    )
    trust_remote_code: bool | None = Field(
        default=None,
        description="Run Python code from the model's repository during the load.",
    )
    low_cpu_mem_usage: bool | None = Field(
        default=None,
        description="Load the weights without a full copy in host memory.",
    )

    @model_validator(mode="after")
    def _names(self):
        for name in self.__pydantic_extra__ or {}:
            if not _NAME_RE.match(name):
                raise ValueError(
                    f"setting '{name}': a setting's name is its environment "
                    "variable in lower case, such as num_steps"
                )
        return self


class HostModelSettings(ModelSettings):
    """[models] in marigold-host.toml: settings for every model, then by
    model type, then by model name."""

    types: dict[ModelType, ModelSettings] = Field(
        default={},
        description="Settings for every model of one type, as [models.types.<type>].",
    )
    names: dict[str, ModelSettings] = Field(
        default={},
        description='Settings for one model, as [models.names."<name>"], the name as models.yaml writes it.',
    )


# What the loaders use when nothing sets a value.
LOADER_DEFAULTS = ModelSettings(
    load_in_4bit=False,
    use_fast=False,
    trust_remote_code=False,
    low_cpu_mem_usage=True,
)


def _set_values(settings: ModelSettings) -> dict:
    return settings.model_dump(exclude_none=True, exclude={"types", "names"})


def resolve_settings(
    model_type: str,
    model_name: str,
    application: ModelSettings,
    host: HostModelSettings,
) -> dict[str, dict]:
    """Each setting's value and the level it came from.

    The levels, each overriding the one before: the loader default, the
    application's models.yaml, the host's [models], its entry for the
    model's type, its entry for the model's name. The host takes
    precedence over the application.

    Returns {name: {"value": ..., "source": ...}}.
    """
    levels = (
        ("default", LOADER_DEFAULTS),
        ("application", application),
        ("host", host),
        ("host type", host.types.get(model_type, ModelSettings())),
        ("host name", host.names.get(model_name, ModelSettings())),
    )

    resolved = {}

    for source, settings in levels:
        for name, value in _set_values(settings).items():
            resolved[name] = {"value": value, "source": source}

    return resolved


def resolved_values(resolved: dict[str, dict]) -> ModelSettings:
    """The values of a resolution, to apply."""
    return ModelSettings(**{name: setting["value"] for name, setting in resolved.items()})


def describe_settings(resolved: dict[str, dict]) -> str:
    """One line: each setting, its value and its source."""
    return " ".join(
        "%s=%s (%s)" % (name, json.dumps(setting["value"]), setting["source"])
        for name, setting in sorted(resolved.items())
    )


def load_host_settings() -> HostModelSettings:
    """The host's [models], as the CLI passed it in MARIGOLD_MODEL_SETTINGS.

    Empty when the variable is unset or empty, which is what a compose
    run without the CLI gives.
    """
    return HostModelSettings.model_validate_json(os.getenv(HOST_SETTINGS_ENV) or "{}")
