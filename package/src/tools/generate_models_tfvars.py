"""
Generate Terraform variable files and model catalogues from assets/models.yaml.

Usage:
    python3 scripts/generate_models_tfvars.py <models.yaml> <command>

Commands:
    terraform-data      Write HCL variable file to stdout.
    infra-data        Write internal model catalogue JSON to stdout.
    public      Fetch provider metadata and write public catalogue JSON to stdout.
    jekyll-data Write flat array for Jekyll _data consumption.
    validate    Validate models.yaml against the schema.

Examples:
    python3 scripts/generate_models_tfvars.py assets/models.yaml terraform-data \\
        > assets/models.tfvars
    python3 scripts/generate_models_tfvars.py assets/models.yaml infra-data \\
        > assets/models.json
    HF_TOKEN=hf_xxx python3 scripts/generate_models_tfvars.py \\
        assets/models.yaml public > assets/public_models_reference.json
    python3 scripts/generate_models_tfvars.py assets/models.yaml validate
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
    from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator
except ImportError:
    print("error: pydantic is required: pip install pydantic", file=sys.stderr)
    sys.exit(1)

try:
    import requests as _requests
except ImportError:
    _requests = None

from shared.enums import ModelProvider, ModelType


# ---------------------------------------------------------------------------
# Input schema
# ---------------------------------------------------------------------------

class ModelParameters(BaseModel):
    vector_size: Optional[int] = None
    model_config = {"extra": "allow"}


class ModelDefinition(BaseModel):
    name: str
    provider: ModelProvider
    type: ModelType
    input: str
    output: str
    gpu_tier: str = Field("none", description="GPU capacity provider tier: none, sm, or lrg")
    gpu_units: int = Field(0, ge=0, le=4, description="Number of GPU units to reserve. 0 = CPU only.")
    memory_size: int = 4096
    timeout: int = Field(10, ge=10)
    auth_required: bool = False
    langcode: Optional[str] = None
    log_level: str = "INFO"
    extra_env: Dict[str, str] = Field(default_factory=dict)
    parameters: ModelParameters = Field(default_factory=ModelParameters)
    description: str = Field("", description="Human-readable description for the public catalogue and semantic search.")
    status: str = "active"

    @field_validator("log_level")
    @classmethod
    def normalise_log_level(cls, v: str) -> str:
        level = v.upper()
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if level not in valid:
            raise ValueError("log_level must be one of %s" % sorted(valid))
        return level


    @field_validator("name")
    @classmethod
    def model_name_lowercase(cls, v: str) -> str:
        if v != v.lower():
            raise ValueError("%s must be lowercase [%s]" % (v, v.lower()))

        return v

    @field_validator("gpu_tier")
    @classmethod
    def validate_gpu_tier(cls, v: str) -> str:
        valid = {"none", "sm", "lrg"}
        if v not in valid:
            raise ValueError("gpu_tier must be one of %s" % sorted(valid))
        return v


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


# ---------------------------------------------------------------------------
# Output schemas
# ---------------------------------------------------------------------------

class TFVarsEntry(BaseModel):
    """Terraform variable entry for one model. Maps directly to HCL output."""

    gpu_tier: str
    gpu_units: int
    memory_reservation: int
    timeout: int
    auth_required: bool
    provider: str
    environment_variables: Dict[str, str]

    def to_hcl(self, key: str) -> str:
        def hcl_str(v: str) -> str:
            return '"%s"' % v.replace("\\", "\\\\").replace('"', '\\"')

        def hcl_bool(v: bool) -> str:
            return "true" if v else "false"

        lines = [
            "  %s = {" % hcl_str(key),
            "    gpu_tier      = %s" % hcl_str(self.gpu_tier),
            "    gpu_units     = %i" % self.gpu_units,
            "    memory_res    = %i" % self.memory_reservation,
            "    timeout       = %i" % self.timeout,
            "    auth_required = %s" % hcl_bool(self.auth_required),
            "    provider      = %s" % hcl_str(self.provider),
            "    environment_variables = {",
        ]
        for k, v in self.environment_variables.items():
            lines.append("      %s = %s" % (hcl_str(k), hcl_str(v)))
        lines.append("    }")
        lines.append("  },")
        return "\n".join(lines)


class InternalCatalogueEntry(BaseModel):
    """Internal catalogue entry. Consumed by cache builder and tooling."""

    name: str
    type: str
    provider: str
    input: str
    output: str
    timeout: int
    auth_required: bool
    gpu_tier: str
    parameters: Dict[str, Any]


class HuggingFaceProviderParameters(BaseModel):
    """Provider metadata fetched from HuggingFace API."""

    auth_required: bool
    organization: str = ""
    license: str = ""
    sha: str = ""
    last_modified: str = ""
    tags: List[str] = Field(default_factory=list)
    parameter_count: int = 0


class PublicCatalogueEntry(BaseModel):
    """Public catalogue entry. Served by the API /models.json route."""

    name: str
    type: str
    provider: str
    input: str
    output: str
    description: str
    parameters: Dict[str, Any]
    provider_parameters: Dict[str, Any]


class JekyllEntry(BaseModel):
    """Flat entry for Jekyll _data consumption."""

    name: str
    type: str
    provider: str
    input: str
    output: str
    description: str
    licence: str = ""


# ---------------------------------------------------------------------------
# Key and CPU derivation
# ---------------------------------------------------------------------------

def make_key(name: str) -> str:
    return md5(name.encode()).hexdigest()


# ---------------------------------------------------------------------------
# ModelDefinition -> output model conversions
# ---------------------------------------------------------------------------

def _make_env_vars(model: ModelDefinition) -> Dict[str, str]:
    env: Dict[str, str] = {
        "MODELNAME":      model.name,
        "MODEL_TYPE":     model.type.value,
        "MODEL_INPUT":    model.input,
        "MODEL_OUTPUT":   model.output,
        "MODEL_PROVIDER": model.provider.value,
    }
    if model.langcode:
        env["MODEL_LANGCODE"] = model.langcode
    if model.log_level != "INFO":
        env["LOG_LEVEL"] = model.log_level
    for k, v in model.extra_env.items():
        env[k] = v
    return env


def to_tfvars_entry(model: ModelDefinition) -> TFVarsEntry:
    return TFVarsEntry(
        gpu_tier=model.gpu_tier,
        gpu_units=model.gpu_units,
        memory_reservation=model.memory_size,
        timeout=model.timeout,
        auth_required=model.auth_required,
        provider=model.provider.value,
        environment_variables=_make_env_vars(model),
    )


def to_internal_entry(model: ModelDefinition) -> InternalCatalogueEntry:
    return InternalCatalogueEntry(
        name=model.name,
        type=model.type.value,
        provider=model.provider.value,
        input=model.input,
        output=model.output,
        timeout=model.timeout,
        auth_required=model.auth_required,
        gpu_tier=model.gpu_tier,
        parameters=model.parameters.model_dump(exclude_none=True),
    )


def to_public_entry(
    model: ModelDefinition,
    provider_parameters: Dict[str, Any],
) -> PublicCatalogueEntry:
    return PublicCatalogueEntry(
        name=model.name,
        type=model.type.value,
        provider=model.provider.value,
        input=model.input,
        output=model.output,
        description=model.description,
        parameters=model.parameters.model_dump(exclude_none=True),
        provider_parameters=provider_parameters,
    )


def to_jekyll_entry(model: ModelDefinition) -> JekyllEntry:
    return JekyllEntry(
        name=model.name,
        type=model.type.value,
        provider=model.provider.value,
        input=model.input,
        output=model.output,
        description=model.description,
    )


# ---------------------------------------------------------------------------
# Provider metadata fetches
# ---------------------------------------------------------------------------

def fetch_huggingface(model: ModelDefinition, token: str = "") -> HuggingFaceProviderParameters:
    if _requests is None:
        print("warning: requests not installed, skipping '%s'" % model.name, file=sys.stderr)
        return HuggingFaceProviderParameters(auth_required=model.auth_required)

    url = "https://huggingface.co/api/models/%s" % model.name
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer %s" % token

    try:
        resp = _requests.get(url, headers=headers, timeout=15, allow_redirects=True)
    except _requests.RequestException as e:
        print("warning: fetch failed for '%s' [%s]" % (model.name, e), file=sys.stderr)
        return HuggingFaceProviderParameters(auth_required=model.auth_required)

    if resp.status_code == 401:
        print("warning: '%s' requires HF_TOKEN (HTTP 401)" % model.name, file=sys.stderr)
        return HuggingFaceProviderParameters(auth_required=model.auth_required)

    if not resp.ok:
        print("warning: '%s' returned HTTP %i" % (model.name, resp.status_code), file=sys.stderr)
        return HuggingFaceProviderParameters(auth_required=model.auth_required)

    try:
        data = resp.json()
    except ValueError as e:
        print("warning: invalid JSON for '%s' [%s]" % (model.name, e), file=sys.stderr)
        return HuggingFaceProviderParameters(auth_required=model.auth_required)

    card_data = data.get("cardData") or {}
    safetensors = data.get("safetensors") or {}

    return HuggingFaceProviderParameters(
        auth_required=model.auth_required,
        organization=data.get("author") or "",
        license=data.get("license") or card_data.get("license") or "",
        sha=data.get("sha") or "",
        last_modified=data.get("lastModified") or "",
        tags=data.get("tags") or [],
        parameter_count=int(safetensors.get("total") or 0),
    )


def fetch_provider_parameters(model: ModelDefinition, token: str = "") -> Dict[str, Any]:
    if model.provider == ModelProvider.HUGGINGFACE:
        return fetch_huggingface(model, token=token).model_dump()
    print(
        "warning: no fetch handler for provider '%s', skipping '%s'" % (model.provider, model.name),
        file=sys.stderr,
    )
    return {"auth_required": model.auth_required}


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------

def render_terraform_data(config: ModelsConfig) -> str:
    lines = [
        "# Generated by scripts/generate_models_tfvars.py",
        "# Source: assets/models.yaml",
        "# Do not edit manually.",
        "",
        "models = {",
    ]
    for model in config.models:
        lines.append(to_tfvars_entry(model).to_hcl(make_key(model.name)))
        lines.append("")
    lines.append("}")
    return "\n".join(lines) + "\n"


def render_internal_json(config: ModelsConfig) -> str:
    result = {
        make_key(m.name): to_internal_entry(m).model_dump()
        for m in config.models
    }
    return json.dumps(result, indent=2) + "\n"


def render_public_json(config: ModelsConfig, token: str = "") -> str:
    result = {}
    for model in config.models:
        print("fetching '%s'..." % model.name, file=sys.stderr)
        result[make_key(model.name)] = to_public_entry(
            model,
            fetch_provider_parameters(model, token=token),
        ).model_dump()
    return json.dumps(result, indent=2) + "\n"


def render_jekyll_json(config: ModelsConfig) -> str:
    models = sorted(config.models, key=lambda m: (m.type.value, m.name))
    result = [to_jekyll_entry(m).model_dump() for m in models]
    return json.dumps(result, indent=2) + "\n"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

COMMANDS = ("terraform-data", "infra-data", "public", "jekyll-data", "validate")


def usage():
    print(
        "usage: generate_models_tfvars.py <models.yaml> <%s>" % "|".join(COMMANDS),
        file=sys.stderr,
    )


def load(yaml_path: Path) -> ModelsConfig:
    with yaml_path.open() as fh:
        raw = yaml.safe_load(fh)

    # strip the _templates key if present -- anchors are resolved by the
    # YAML parser before this point; the key itself is not needed
    if isinstance(raw, dict):
        raw.pop("_templates", None)

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
    elif command == "terraform-data":
        sys.stdout.write(render_terraform_data(config))
    elif command == "infra-data":
        sys.stdout.write(render_internal_json(config))
    elif command == "jekyll-data":
        sys.stdout.write(render_jekyll_json(config))
    elif command == "public":
        token = os.environ.get("HF_TOKEN", "")
        sys.stdout.write(render_public_json(config, token=token))


if __name__ == "__main__":
    main()
