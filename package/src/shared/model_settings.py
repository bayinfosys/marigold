"""Model settings: how a model is loaded and run, by name and value.

A setting's name is its environment variable in lower case:
load_in_4bit is LOAD_IN_4BIT. The four settings the loaders read are
typed. Handlers read further settings, such as num_steps, which are
allowed as extra keys holding a string, a number or a boolean.

A models.yaml entry declares its settings under `settings:`. The worker
and the cache container apply them to the process environment before a
load, through shared.db_models.set_model_config_env.

This module imports only pydantic, so the CLI can import it.
"""

import re

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
