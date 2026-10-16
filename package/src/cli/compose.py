"""Compose invocation: two kinds of project, two environments.

The platform (postgres, api, worker, cache-init) runs as project
'marigold': one per host, shared by every application. An
application's containers run as project 'marigold-<application>'.

Compose treats everything under a project name as one set, starting
what is missing and removing what a run no longer declares, which is
why these cannot share a name. They are joined by the
marigold-applications network, declared in docker-compose.core.yaml and
joined as external by the executor.

platform_env needs no application, which is what lets the platform
start, stop and be inspected on its own. compose_env adds the
application's variables on top of it.
"""

import json
import os
import shlex
import subprocess

from importlib.resources import files
from pathlib import Path

from cli.applications import application_name
from cli.config import marigold_version, setting
from cli.paths import cache_dir_from_config, cache_paths

COMPOSE_FILES = {
    "core": "docker-compose.core.yaml",
    "cpu": "docker-compose.cpu.yaml",
    "gpu": "docker-compose.gpu.yaml",
    "webui": "docker-compose.webui.yaml",
    "executor": "docker-compose.executor.yaml",
}

PLATFORM_PROJECT = "marigold"

DEFAULT_PLATFORM_COMPOSE_FILES = ["core", "cpu"]

# Compose files describing an application's containers. Not
# configurable: an application is one service definition, parameterised
# through the environment.
APPLICATION_COMPOSE_FILES = ["executor"]

DEFAULT_EXECUTION_IMAGE = "ghcr.io/bayinfosys/marigold-executor-python"


def application_project(name: str) -> str:
    return f"{PLATFORM_PROJECT}-{name}"


def default_tag() -> str:
    """The image tag is the PyPI version, unprefixed.

    The Docker build takes its tag from the Python version, and PEP 440
    normalises away any 'v', so the two agree only when nothing adds one
    back.
    """
    return marigold_version()


def platform_compose_files(config: dict) -> list[str]:
    """Compose files describing the platform, plus any an application adds.

    [platform].compose_files is the host's own list. An application's
    [application].compose_files are additions: an overlay it needs (gpu)
    or a service it brings (webui). Appended in order, so an overlay
    lands after the file it overlays.
    """
    names = list(setting(config, "platform", "compose_files", DEFAULT_PLATFORM_COMPOSE_FILES))

    for name in setting(config, "application", "compose_files", []):
        if name not in names:
            names.append(name)

    return names


def execution_command(config: dict) -> str | None:
    """[execution].command as a single string for compose.

    A list is the documented form; joined with shlex so arguments
    containing spaces survive. A plain string is passed through for
    anyone who writes one.
    """
    command = config.get("execution", {}).get("command")

    if not command:
        return None

    if isinstance(command, (list, tuple)):
        return shlex.join(str(part) for part in command)

    return str(command)


def execution_image(config: dict, tag: str) -> str:
    """The executor image reference, tag included.

    A reference carrying a tag or a digest is taken as written: an
    application pinning marigold-executor-node:1.4 means that version,
    whatever the platform is running. An untagged reference gets the
    platform's tag, which keeps the default image in step with the rest
    of the platform without anyone declaring it.
    """
    image = str(config.get("execution", {}).get("image", DEFAULT_EXECUTION_IMAGE))

    if "@" in image:
        return image

    # A colon in the last path segment is a tag; one before that is a
    # registry port (registry:5000/marigold-executor-python).
    if ":" in image.rsplit("/", 1)[-1]:
        return image

    return f"{image}:{tag}"


def compose_base_cmd(
    project: str,
    compose_file_names: list[str],
    project_directory: Path | None = None,
) -> list[str]:
    compose_dir = files("compose")
    cmd = ["docker", "compose", "-p", project]

    if project_directory is not None:
        cmd += ["--project-directory", str(project_directory)]

    for name in compose_file_names:
        filename = COMPOSE_FILES.get(name)
        if filename is None:
            raise ValueError(
                f"unknown compose file '{name}' "
                f"(known: {', '.join(sorted(COMPOSE_FILES))})"
            )
        cmd += ["-f", str(compose_dir / filename)]

    return cmd


def platform_env(config: dict) -> dict:
    """Everything the platform's compose files read.

    No application: nothing in the platform's services reads one. The
    cache container mounts the applications directory, which is where an
    installed application lives, and is told which one to read when
    `cache populate` runs it.
    """
    env = dict(os.environ)
    env["TAG"] = setting(config, "platform", "tag", default_tag())

    cache_dir = cache_dir_from_config(config)
    env["MARIGOLD_CACHE_DIR"] = str(cache_dir)

    # MARIGOLD_MODELS_DIR, MARIGOLD_TMP_DIR, MARIGOLD_OUTPUTS_DIR,
    # MARIGOLD_APPLICATIONS_DIR: one per entry in paths.CACHE_SUBDIRS.
    for name, path in cache_paths(cache_dir).items():
        env[f"MARIGOLD_{name.upper()}_DIR"] = str(path)

    # Only set the database URL if some config layer provided one. Left
    # unset otherwise, so docker-compose.core.yaml's own fallback
    # applies rather than duplicating that default here.
    db_url = config.get("database", {}).get("url")
    if db_url:
        env["MARIGOLD_DATABASE_URL"] = db_url

    # Application-declared variables for services other than
    # api/worker/cache -- e.g. RAG_EMBEDDING_MODEL for open-webui. The
    # CLI doesn't know or care what these mean; it just forwards them.
    for key, value in config.get("environment", {}).items():
        env[str(key)] = str(value)

    return env


def compose_env(application_dir: Path, config: dict) -> dict:
    """The platform environment, plus the application's own variables."""
    env = platform_env(config)

    env["MARIGOLD_APPLICATION_DIR"] = str(application_dir)

    # MARIGOLD_APPLICATION_ID is the name while an application runs one
    # instance; instance expansion appends a suffix to it and leaves
    # MARIGOLD_APPLICATION_NAME alone, so code and usage rows can group
    # by application either way.
    name = application_name(application_dir, config)
    env["MARIGOLD_APPLICATION_NAME"] = name
    env["MARIGOLD_APPLICATION_ID"] = name
    env["MARIGOLD_EXECUTION_IMAGE"] = execution_image(config, env["TAG"])

    command = execution_command(config)
    if command:
        env["MARIGOLD_EXECUTION_COMMAND"] = command

    return env


def run_compose(
    application_dir: Path | None,
    config: dict,
    extra_args: list[str],
    env: dict | None = None,
    project: str = PLATFORM_PROJECT,
    compose_file_names: list[str] | None = None,
) -> int:
    """Run one docker compose command.

    project and compose_file_names default to the platform. Application
    calls pass both, since an application is a different set of
    containers described by a different file.
    """
    if env is None:
        env = compose_env(application_dir, config) if application_dir else platform_env(config)

    names = compose_file_names or platform_compose_files(config)
    cmd = compose_base_cmd(project, names, project_directory=application_dir) + extra_args

    return subprocess.run(cmd, env=env).returncode


def run_application_compose(
    application_dir: Path,
    config: dict,
    extra_args: list[str],
    env: dict | None = None,
) -> int:
    """Run one docker compose command against this application's containers."""
    name = application_name(application_dir, config)

    return run_compose(
        application_dir, config, extra_args,
        env=env,
        project=application_project(name),
        compose_file_names=APPLICATION_COMPOSE_FILES,
    )


def run_project_compose(project: str, extra_args: list[str]) -> int:
    """Run compose against a project by name, with no compose files.

    down, ps and logs resolve what they act on from container labels,
    so they need neither the files nor the environment. This is what
    lets the platform, and an application that has since been
    uninstalled, be stopped and inspected.
    """
    return subprocess.run(["docker", "compose", "-p", project] + extra_args).returncode


def application_projects() -> list[str]:
    """Application compose projects that exist, running or not.

    Reads `docker compose ls`, filtered on the platform prefix. The
    platform project itself is excluded: it is not an application.
    """
    result = subprocess.run(
        ["docker", "compose", "ls", "--format", "json", "--all"],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        return []

    try:
        entries = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []

    prefix = f"{PLATFORM_PROJECT}-"

    return sorted(
        entry["Name"] for entry in entries
        if entry.get("Name", "").startswith(prefix)
    )
