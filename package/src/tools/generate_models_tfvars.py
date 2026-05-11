"""
Generate Terraform variable files and model catalogues from assets/models.yaml.

Usage:
    python3 scripts/generate_models_tfvars.py <models.yaml> <command>

Commands:
    tfvars      Write HCL variable file to stdout.
                Redirect to assets/models.tfvars.
    json        Write internal model catalogue JSON to stdout.
                Contains all fields including infrastructure metadata.
                Redirect to assets/models.json.
    public      Fetch provider metadata and write public catalogue JSON to stdout.
                Contains only provider metadata and model characteristics.
                No infrastructure fields. Requires network access.
                Redirect to assets/public_models_reference.json.
                Reads HF_TOKEN from the environment (optional but recommended).
    validate    Validate models.yaml against the schema. No output files.
                Exits non-zero on any validation error.

Examples:
    python3 scripts/generate_models_tfvars.py assets/models.yaml tfvars \\
        > assets/models.tfvars
    python3 scripts/generate_models_tfvars.py assets/models.yaml json \\
        > assets/models.json
    HF_TOKEN=hf_xxx python3 scripts/generate_models_tfvars.py \\
        assets/models.yaml public > assets/public_models_reference.json
    python3 scripts/generate_models_tfvars.py assets/models.yaml validate

Output format (tfvars):
    HCL consumed by Terraform layers 02 and 03. Contains only the fields
    that Terraform infrastructure resources read directly:
    memory_size, timeout, idle_timeout, auth_required, environment_variables.

Output format (json):
    JSON object keyed by md5(model name). Internal use only -- consumed by
    the cache builder and internal tooling. Not served publicly.

Output format (public):
    JSON object keyed by md5(model name). Served by the API /models.json
    route. Contains: name, type, provider, input, output, parameters,
    provider_parameters.

    provider_parameters for huggingface:
        auth_required     whether a token is required to download the model
        organization      model author / org
        license           SPDX identifier or empty string
        sha               latest commit sha
        last_modified     ISO 8601 timestamp
        tags              list of tag strings
        parameter_count   total parameter count from safetensors metadata (int)

    Fetching makes one HTTP request per model. Run when models.yaml changes.
    Commit public_models_reference.json so that terraform apply requires no
    network connection.

Providers:
    huggingface     Fetches from https://huggingface.co/api/models/{name}.
                    Set HF_TOKEN to avoid rate limits or access gated models.
    (future)        aws-bedrock

Requirements:
    pip install pyyaml pydantic requests
"""

import json
import os
import sys
from hashlib import md5
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml
except ImportError:
    print("error: pyyaml is required: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

try:
    from pydantic import (BaseModel, Field, ValidationError, field_validator,
                          model_validator)
except ImportError:
    print("error: pydantic is required: pip install pydantic", file=sys.stderr)
    sys.exit(1)

try:
    import requests as _requests
except ImportError:
    _requests = None

from shared.enums import ModelProvider, ModelType

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class ModelParameters(BaseModel):
    """Model-specific metadata for the API layer. Not used by Terraform."""

    vector_size: Optional[int] = None
    model_config = {"extra": "allow"}


class ModelDefinition(BaseModel):
    name: str
    provider: ModelProvider
    type: ModelType
    input: str
    output: str
    memory_size: int = Field(9216, ge=512)
    requires_gpu: bool = False
    timeout: int = Field(300, ge=30)
    idle_timeout: int = Field(0, ge=0)
    auth_required: bool = False
    langcode: Optional[str] = None
    log_level: str = "INFO"
    extra_env: Dict[str, str] = Field(default_factory=dict)
    parameters: ModelParameters = Field(default_factory=ModelParameters)
    description: str = Field("", description="one or two sentence human description for the public catalogue")

    @field_validator("log_level")
    @classmethod
    def normalise_log_level(cls, v: str) -> str:
        level = v.upper()
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if level not in valid:
            raise ValueError("log_level must be one of %s" % sorted(valid))
        return level


class ModelsConfig(BaseModel):
    models: List[ModelDefinition]

    @model_validator(mode="after")
    def no_duplicate_names(self) -> "ModelsConfig":
        seen = set()
        for m in self.models:
            if m.name in seen:
                raise ValueError("duplicate model name: '%s'" % m.name)
            seen.add(m.name)
        return self


#
# ecs memory/cpu relationship
#
def cpu_for_memory(memory_mb: int) -> int:
    """Return the minimum Fargate CPU units valid for the given memory."""
    if memory_mb <= 2048:
        return 256
    elif memory_mb <= 4096:
        return 512
    elif memory_mb <= 8192:
        return 1024
    elif memory_mb <= 16384:
        return 2048
    elif memory_mb <= 30720:
        return 4096
    elif memory_mb <= 61440:
        return 8192
    else:
        return 16384


# ---------------------------------------------------------------------------
# Key derivation
# ---------------------------------------------------------------------------


def make_key(name: str) -> str:
    """Derive a deterministic fixed-length key from a model name.

    md5 of the raw name string. Used consistently in:
      - models.tfvars (Terraform map key)
      - models_config.json (polling routing table)
      - models.json and public_models_reference.json (catalogue keys)
      - DynamoDB results table keys

    Do not normalise the name before hashing. The polling lambda hashes the
    raw name from the request body and must produce the same key.
    """
    return md5(name.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Provider metadata fetches
# ---------------------------------------------------------------------------


def fetch_huggingface(model: ModelDefinition, token: str = "") -> dict:
    """Fetch model metadata from the HuggingFace model API."""
    if _requests is None:
        print(
            "warning: requests not installed, skipping fetch for '%s'" % model.name,
            file=sys.stderr,
        )
        return _empty_huggingface(model)

    url = "https://huggingface.co/api/models/%s" % model.name
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer %s" % token

    try:
        resp = _requests.get(url, headers=headers, timeout=15, allow_redirects=True)
    except _requests.RequestException as e:
        print("warning: fetch failed for '%s' [%s]" % (model.name, e), file=sys.stderr)
        return _empty_huggingface(model)

    if resp.status_code == 401:
        print(
            "warning: '%s' requires HF_TOKEN (HTTP 401)" % model.name, file=sys.stderr
        )
        return _empty_huggingface(model)

    if not resp.ok:
        print(
            "warning: '%s' returned HTTP %i" % (model.name, resp.status_code),
            file=sys.stderr,
        )
        return _empty_huggingface(model)

    try:
        data = resp.json()
    except ValueError as e:
        print("warning: invalid JSON for '%s' [%s]" % (model.name, e), file=sys.stderr)
        return _empty_huggingface(model)

    card_data = data.get("cardData") or {}
    safetensors = data.get("safetensors") or {}
    parameter_count = int(safetensors.get("total") or 0)

    return {
        "auth_required": model.auth_required,
        "organization": data.get("author") or "",
        "license": data.get("license") or card_data.get("license") or "",
        "sha": data.get("sha") or "",
        "last_modified": data.get("lastModified") or "",
        "tags": data.get("tags") or [],
        "parameter_count": parameter_count,
    }


def _empty_huggingface(model: ModelDefinition) -> dict:
    return {
        "auth_required": model.auth_required,
        "organization": "",
        "license": "",
        "sha": "",
        "last_modified": "",
        "tags": [],
        "parameter_count": 0,
    }


def fetch_provider_parameters(model: ModelDefinition, token: str = "") -> dict:
    if model.provider == ModelProvider.HUGGINGFACE:
        return fetch_huggingface(model, token=token)

    print(
        "warning: no fetch handler for provider '%s', skipping '%s'"
        % (model.provider, model.name),
        file=sys.stderr,
    )
    return {"auth_required": model.auth_required}


# ---------------------------------------------------------------------------
# Environment variable construction
# ---------------------------------------------------------------------------


def make_env_vars(model: ModelDefinition) -> Dict[str, str]:
    """Construct the environment_variables map for this model's ECS task."""
    env: Dict[str, str] = {
        "MODELNAME": model.name,
        "MODEL_TYPE": model.type.value,
        "MODEL_INPUT": model.input,
        "MODEL_OUTPUT": model.output,
        "MODEL_PROVIDER": model.provider.value,
    }

    if model.langcode:
        env["MODEL_LANGCODE"] = model.langcode

    if model.log_level != "INFO":
        env["LOG_LEVEL"] = model.log_level

    for k, v in model.extra_env.items():
        env[k] = v

    return env


# ---------------------------------------------------------------------------
# HCL rendering
# ---------------------------------------------------------------------------


def hcl_str(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return '"%s"' % escaped


def render_tfvars(config: ModelsConfig) -> str:
    lines = [
        "# Generated by scripts/generate_models_tfvars.py",
        "# Source: assets/models.yaml",
        "# Do not edit manually.",
        "",
        "models = {",
    ]

    for model in config.models:
        key = make_key(model.name)
        env = make_env_vars(model)

        lines.append("  %s = {" % hcl_str(key))
        lines.append("    cpu_size      = %i" % cpu_for_memory(model.memory_size))
        lines.append("    memory_size   = %i" % model.memory_size)
        lines.append("    requires_gpu  = %s" % ("true" if model.requires_gpu else "false"))
        lines.append("    timeout       = %i" % model.timeout)
        lines.append("    idle_timeout  = %i" % model.idle_timeout)
        lines.append("    auth_required = %s" % ("true" if model.auth_required else "false"))
        lines.append("    provider      = %s" % hcl_str(model.provider.value))
        lines.append("    environment_variables = {")
        for k, v in env.items():
            lines.append("      %s = %s" % (hcl_str(k), hcl_str(v)))
        lines.append("    }")
        lines.append("  },")
        lines.append("")

    lines.append("}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# JSON rendering
# ---------------------------------------------------------------------------


def render_internal_json(config: ModelsConfig) -> str:
    """Write the internal model catalogue.

    Keyed by md5(model name). Contains all fields including infrastructure
    metadata. Not served publicly -- consumed by the cache builder and
    internal tooling.
    """
    result: Dict[str, Any] = {}

    for model in config.models:
        key = make_key(model.name)
        result[key] = {
            "name": model.name,
            "type": model.type.value,
            "provider": model.provider.value,
            "input": model.input,
            "output": model.output,
            "memory_size": model.memory_size,
            "timeout": model.timeout,
            "idle_timeout": model.idle_timeout,
            "auth_required": model.auth_required,
            "parameters": model.parameters.model_dump(exclude_none=True),
        }

    return json.dumps(result, indent=2) + "\n"


def render_public_json(config: ModelsConfig, token: str = "") -> str:
    """Fetch provider metadata and write the public model catalogue.

    Keyed by md5(model name). Served by the API /models.json route.
    Contains no infrastructure fields.
    """
    result: Dict[str, Any] = {}

    for model in config.models:
        key = make_key(model.name)
        print("fetching '%s'..." % model.name, file=sys.stderr)
        provider_parameters = fetch_provider_parameters(model, token=token)

        result[key] = {
            "name": model.name,
            "type": model.type.value,
            "provider": model.provider.value,
            "input": model.input,
            "output": model.output,
            "parameters": model.parameters.model_dump(exclude_none=True),
            "provider_parameters": provider_parameters,
        }

    return json.dumps(result, indent=2) + "\n"


def render_jekyll_json(config: ModelsConfig) -> str:
    """Write a flat array for Jekyll _data consumption.

    Array of model objects, each with all public fields.
    No infrastructure fields. No MD5 keys.
    Ordered by type then name for stable diffs.
    """
    models = sorted(config.models, key=lambda m: (m.type.value, m.name))
    result = []
    for model in models:
        result.append({
            "name":        model.name,
            "type":        model.type.value,
            "provider":    model.provider.value,
            "input":       model.input,
            "output":      model.output,
            "description": model.description,
            "licence":     model.parameters.licence if hasattr(model.parameters, "licence") else "",
        })
    return json.dumps(result, indent=2) + "\n"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

COMMANDS = ("tfvars", "json", "public", "jekyll-data", "validate")


def usage():
    print(
        "usage: generate_models_tfvars.py <models.yaml> <%s>" % "|".join(COMMANDS),
        file=sys.stderr,
    )


def load(yaml_path: Path) -> ModelsConfig:
    with yaml_path.open() as fh:
        raw = yaml.safe_load(fh)

    try:
        return ModelsConfig.model_validate(raw)
    except ValidationError as e:
        print("error: validation failed\n%s" % e, file=sys.stderr)
        sys.exit(1)


def main():
    if len(sys.argv) != 3:
        usage()
        sys.exit(1)

    yaml_path = Path(sys.argv[1])
    command = sys.argv[2]

    if command not in COMMANDS:
        usage()
        sys.exit(1)

    if not yaml_path.exists():
        print("error: %s not found" % yaml_path, file=sys.stderr)
        sys.exit(1)

    config = load(yaml_path)

    if command == "validate":
        print("ok: %i models" % len(config.models))
        sys.exit(0)
    elif command == "tfvars":
        sys.stdout.write(render_tfvars(config))
        sys.exit(0)
    elif command == "json":
        sys.stdout.write(render_internal_json(config))
        sys.exit(0)
    elif command == "jekyll-data":
        sys.stdout.write(render_jekyll_json(config))
        sys.exit(0)
    elif command == "public":
        token = os.environ.get("HF_TOKEN", "")
        sys.stdout.write(render_public_json(config, token=token))
        sys.exit(0)
    else:
        print("unknown command")
        sys.exit(1)


if __name__ == "__main__":
    main()
