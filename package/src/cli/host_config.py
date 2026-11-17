"""marigold-host.toml as a validated object.

The host config holds everything about how one machine runs the
platform. It is the only source of host settings: the CLI reads the
file through HostConfig, and compose files see the result only as the
environment HostConfig.compose_env() builds. docs/configuration.md is
generated from the field descriptions here.

Where it is read from, first match wins:

    --host-config PATH          on the command line (sets the variable below)
    $MARIGOLD_HOST_CONFIG       must exist when set
    ./marigold-host.toml
    ~/.marigold/marigold-host.toml

No file at all means every default. Unknown sections and keys are
errors.

Sections, one per layer:

    [platform]   compose files, image tag, logging, worker idle timeout
    [storage]    the cache directory and where outputs are stored
    [database]   the platform Postgres, or an external database URL
    [[registry]] registries searched for applications, in file order
    [network]    the ports and address the platform publishes
    [resources]  memory, CPU and process limits per service
    [environment] variables forwarded to every service

Secrets stay in the shell environment and never go in this file:
HF_TOKEN, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_DEFAULT_REGION,
AZURE_STORAGE_ACCOUNT, AZURE_STORAGE_CONNECTION_STRING.

This module imports nothing from the rest of the CLI, so every other
module can import it.
"""

import ipaddress
import os
import re
import tomllib

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

HOST_CONFIG_NAME = "marigold-host.toml"
HOST_CONFIG_ENV = "MARIGOLD_HOST_CONFIG"
DEFAULT_HOST_CONFIG_PATH = Path.home() / ".marigold" / HOST_CONFIG_NAME
DEFAULT_CACHE_DIR = Path.home() / ".marigold" / "cache"

REGISTRY_SCHEMES = ("http://", "https://")

# Registry names follow application names: lowercase, digits, single hyphens.
_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

# Docker's size syntax: a number and an optional unit, as in "512m", "4g".
_SIZE_RE = re.compile(r"^\d+(\.\d+)?[bkmg]?$")


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _check_size(value: str | None, field: str) -> str | None:
    if value is None:
        return None

    value = str(value).strip().lower()
    if not _SIZE_RE.match(value):
        raise ValueError(f"{field} '{value}': a number and a unit, such as '512m' or '4g'")

    return value


class PlatformSection(_Section):
    compose_files: list[str] = Field(
        default=["core", "cpu"],
        description='Platform compose files. Add "gpu" for an NVIDIA worker: ["core", "cpu", "gpu"].',
    )
    tag: str | None = Field(
        default=None,
        description="Image tag for the platform images. Unset means the installed CLI's version.",
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO",
        description="Log level for the worker and application instances.",
    )
    idle_timeout: int = Field(
        default=120,
        ge=0,
        description="Seconds the worker keeps a model loaded with an empty queue. 0 never unloads.",
    )


class StorageSection(_Section):
    location: Path = Field(
        default=DEFAULT_CACHE_DIR,
        description="The cache directory: models, the platform database, outputs and installed applications. A local path or a mounted network share.",
    )
    outputs: Literal["fs", "s3", "azure"] = Field(
        default="fs",
        description="Where images, audio and video outputs are stored: files under the cache, S3, or Azure Blob Storage.",
    )
    bucket: str | None = Field(
        default=None,
        description="s3: the bucket, which must already exist.",
    )
    endpoint: str | None = Field(
        default=None,
        description="s3: the endpoint of an S3-compatible service. Unset means AWS S3.",
    )
    region: str | None = Field(
        default=None,
        description="s3: the region, passed as AWS_DEFAULT_REGION. Unset leaves the shell's AWS_DEFAULT_REGION.",
    )
    container: str | None = Field(
        default=None,
        description="azure: the blob container, which must already exist.",
    )

    @field_validator("location", mode="before")
    @classmethod
    def _location(cls, value):
        return Path(str(value)).expanduser()

    @model_validator(mode="after")
    def _backend(self):
        if self.outputs == "s3" and not self.bucket:
            raise ValueError('outputs = "s3" needs bucket')

        if self.outputs == "azure" and not self.container:
            raise ValueError('outputs = "azure" needs container')

        if self.outputs != "s3" and (self.bucket or self.endpoint or self.region):
            raise ValueError('bucket, endpoint and region apply only to outputs = "s3"')

        if self.outputs != "azure" and self.container:
            raise ValueError('container applies only to outputs = "azure"')

        return self


class DatabaseSection(_Section):
    url: str | None = Field(
        default=None,
        description="An external Postgres connection string. Unset means the platform's own Postgres, built from the keys below.",
    )
    name: str = Field(default="marigold", description="Platform Postgres: database name.")
    user: str = Field(default="marigold", description="Platform Postgres: user.")
    password: str = Field(default="marigold", description="Platform Postgres: password.")

    @property
    def resolved_url(self) -> str:
        return self.url or f"postgresql://{self.user}:{self.password}@postgres:5432/{self.name}"


class RegistryEntry(_Section):
    """One registry. [[registry]] entries are searched in file order."""

    url: str = Field(description="The registry's address: http:// or https://.")
    name: str | None = Field(
        default=None,
        description="A local name for the registry, as with git remotes. Recorded only; nothing resolves by it yet.",
    )

    @field_validator("url")
    @classmethod
    def _url(cls, value):
        if not value.startswith(REGISTRY_SCHEMES):
            raise ValueError(f"registry '{value}' must be http:// or https://")
        return value if value.endswith("/") else value + "/"

    @field_validator("name")
    @classmethod
    def _name(cls, value):
        if value is not None and not _NAME_RE.match(value):
            raise ValueError(f"registry name '{value}': lowercase letters, digits and single hyphens")
        return value


class NetworkSection(_Section):
    bind: str = Field(
        default="127.0.0.1",
        description='Host address the API and Open WebUI publish on. "0.0.0.0" publishes on every interface, so other machines can reach them.',
    )
    api_port: int = Field(default=8000, ge=1, le=65535, description="Host port for the API.")
    webui_port: int = Field(default=3000, ge=1, le=65535, description="Host port for Open WebUI, when an application adds it.")

    @field_validator("bind")
    @classmethod
    def _bind(cls, value):
        try:
            ipaddress.ip_address(value)
        except ValueError:
            raise ValueError(f"bind '{value}': an IP address, such as '127.0.0.1' or '0.0.0.0'") from None
        return value


class ServiceLimits(_Section):
    memory: str | None = Field(default=None, description="Memory limit, such as '4g'. Unset means no limit.")
    cpus: float | None = Field(default=None, gt=0, description="CPU limit, in cores. Unset means no limit.")
    pids: int | None = Field(default=None, gt=0, description="Process and thread limit. Unset means no limit.")

    @field_validator("memory", mode="before")
    @classmethod
    def _memory(cls, value):
        return _check_size(value, "memory")


class WorkerLimits(ServiceLimits):
    shm: str = Field(default="2g", description="Shared memory (/dev/shm) for the worker, used by PyTorch.")

    @field_validator("shm", mode="before")
    @classmethod
    def _shm(cls, value):
        return _check_size(value, "shm")


class ResourcesSection(_Section):
    executor: ServiceLimits = Field(
        default_factory=lambda: ServiceLimits(memory="4g", cpus=2.0, pids=512),
        description="Each application instance.",
    )
    worker: WorkerLimits = Field(
        default_factory=WorkerLimits,
        description="The inference worker. Model weights load through host memory, so set memory below the host's total.",
    )
    api: ServiceLimits = Field(
        default_factory=lambda: ServiceLimits(memory="1g"),
        description="The API.",
    )
    postgres: ServiceLimits = Field(
        default_factory=lambda: ServiceLimits(memory="1g"),
        description="The platform Postgres.",
    )
    webui: ServiceLimits = Field(
        default_factory=lambda: ServiceLimits(memory="2g"),
        description="Open WebUI, when an application adds it.",
    )


RegistryList = list[RegistryEntry]


class HostConfig(_Section):
    platform: PlatformSection = Field(default_factory=PlatformSection)
    storage: StorageSection = Field(default_factory=StorageSection)
    database: DatabaseSection = Field(default_factory=DatabaseSection)
    registry: RegistryList = Field(
        default=[],
        description="Registries searched for applications, in file order. The first registry listing a name supplies it.",
    )
    network: NetworkSection = Field(default_factory=NetworkSection)
    resources: ResourcesSection = Field(default_factory=ResourcesSection)
    environment: dict[str, str | int | float | bool] = Field(
        default={},
        description="Variables forwarded to every service. An application's [environment] wins per key.",
    )

    @field_validator("registry")
    @classmethod
    def _unique_registries(cls, value):
        urls = [entry.url for entry in value]
        names = [entry.name for entry in value if entry.name]
        for kind, items in (("url", urls), ("name", names)):
            repeated = sorted({item for item in items if items.count(item) > 1})
            if repeated:
                raise ValueError(f"registry {kind} listed more than once: {', '.join(repeated)}")
        return value

    def registry_urls(self) -> list[str]:
        """Registry addresses in search order."""
        return [entry.url for entry in self.registry]

    def compose_env(self, tag: str) -> dict[str, str]:
        """The variables the platform compose files read.

        tag is the resolved image tag: platform.tag, or the CLI's
        version when that is unset. Compose files read each as
        ${NAME:-default}, with the same defaults as this model, so they
        also run without the CLI.
        """
        env = {
            "TAG": tag,
            "MARIGOLD_LOG_LEVEL": self.platform.log_level,
            "MARIGOLD_IDLE_TIMEOUT": str(self.platform.idle_timeout),
            "MARIGOLD_CACHE_DIR": str(self.storage.location),
            "MARIGOLD_STORAGE": self.storage.outputs,
            "MARIGOLD_STORAGE_BUCKET": self.storage.bucket or "",
            "MARIGOLD_STORAGE_ENDPOINT": self.storage.endpoint or "",
            "MARIGOLD_STORAGE_CONTAINER": self.storage.container or "",
            "MARIGOLD_DATABASE_URL": self.database.resolved_url,
            "POSTGRES_DB": self.database.name,
            "POSTGRES_USER": self.database.user,
            "POSTGRES_PASSWORD": self.database.password,
            "MARIGOLD_BIND": self.network.bind,
            "MARIGOLD_API_PORT": str(self.network.api_port),
            "MARIGOLD_WEBUI_PORT": str(self.network.webui_port),
            "MARIGOLD_WORKER_SHM": self.resources.worker.shm,
        }

        if self.storage.region:
            env["AWS_DEFAULT_REGION"] = self.storage.region

        for service in ("executor", "worker", "api", "postgres", "webui"):
            limits: ServiceLimits = getattr(self.resources, service)
            prefix = f"MARIGOLD_{service.upper()}"
            # Docker reads 0 as no limit for memory and CPUs, -1 for pids.
            env[f"{prefix}_MEMORY"] = limits.memory or "0"
            env[f"{prefix}_CPUS"] = str(limits.cpus or 0)
            env[f"{prefix}_PIDS"] = str(limits.pids or -1)

        for key, value in self.environment.items():
            env[str(key)] = str(value)

        return env


def host_config_path() -> Path | None:
    """The host config file in use, or None when there is none.

    $MARIGOLD_HOST_CONFIG wins and must exist; then marigold-host.toml
    in the current directory; then ~/.marigold/marigold-host.toml.
    """
    override = os.environ.get(HOST_CONFIG_ENV)

    if override:
        path = Path(override).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"{HOST_CONFIG_ENV} is set to '{path}', which does not exist")
        return path

    for path in (Path.cwd() / HOST_CONFIG_NAME, DEFAULT_HOST_CONFIG_PATH):
        if path.is_file():
            return path

    return None


def parse_host_config(text: str, source) -> HostConfig:
    """Parse and validate host config content. source names it in errors."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"cannot parse {source}: {e}") from e

    try:
        return HostConfig.model_validate(data)
    except ValidationError as e:
        lines = [
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in e.errors()
        ]
        raise ValueError(f"{source}:\n  " + "\n  ".join(lines)) from None


def load_host_config(path: Path | None = None) -> HostConfig:
    """The host config from path, or from host_config_path(); defaults if none."""
    path = path or host_config_path()

    if path is None:
        return HostConfig()

    return parse_host_config(path.read_text(encoding="utf-8"), path)
