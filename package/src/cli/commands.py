"""Command implementations: the only layer that exits.

Everything below raises; these functions decide what a failure means
for the user and pick the exit code.
"""

import os
import sys

from pathlib import Path

from shared.model_cache import cache_dir_bytes

from cli import packages
from cli.compose import (
    DEFAULT_EXECUTION_IMAGE,
    DEFAULT_PLATFORM_COMPOSE_FILES,
    PLATFORM_PROJECT,
    application_project,
    application_projects,
    compose_env,
    default_tag,
    execution_command,
    execution_image,
    platform_compose_files,
    platform_env,
    run_application_compose,
    run_compose,
    run_project_compose,
)
from cli.config import (
    PACKAGE_CONFIG_NAME,
    SYSTEM_CONFIG_NAME,
    load_config,
    load_system_config,
    load_toml,
    merge_config,
    package_version,
    resolve_with_source,
    setting,
    system_config_path,
)
from cli.paths import (
    DEFAULT_CACHE_DIR,
    cache_dir_from_config,
    cache_dir_from_system_config,
    cache_paths,
    container_path,
    ensure_cache_layout,
)


def _package(target: str) -> tuple[Path, dict, dict]:
    """(root, merged config, compose environment) for one target."""
    package_dir = packages.resolve_target(target)
    config = load_config(package_dir)

    return package_dir, config, compose_env(package_dir, config)


def _application_target(target: str) -> str:
    """The compose project for a target, for commands that only need one.

    Resolving the package gives the application name. When the package
    has been uninstalled and its containers are still there, a target
    that looks like an application name is taken as one, so they can
    still be stopped and inspected.
    """
    try:
        _, _, env = _package(target)
        return application_project(env["MARIGOLD_APPLICATION_NAME"])
    except FileNotFoundError:
        if not packages.NAME_RE.match(target):
            raise

        project = application_project(target)

        if project not in application_projects():
            raise

        return project


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------

def cmd_config_path(args):
    """Print the system config file in use, absolute."""
    path = system_config_path()
    override = os.environ.get("MARIGOLD_CONFIG")

    if override:
        source = "MARIGOLD_CONFIG"
    elif path == Path(SYSTEM_CONFIG_NAME):
        source = "current directory"
    else:
        source = "home directory"

    state = "found" if path.exists() else "NOT FOUND"

    print(f"{path.resolve()}  ({source}, {state})")
    sys.exit(0 if path.exists() else 1)


def cmd_config_show(args):
    """Print resolved configuration with the layer each value came from.

    Takes an optional package target so package-level values are
    visible. Without one, only the system layer and defaults apply.
    """
    system_path = system_config_path()
    system = load_toml(system_path)

    package: dict = {}
    package_path = None
    package_dir = None

    if args.target is not None:
        package_dir = packages.resolve_target(args.target)
        candidate = package_dir / PACKAGE_CONFIG_NAME

        if candidate.exists():
            package_path = candidate
            package = load_toml(candidate)

    print("sources")
    print(f"  system  : {system_path.resolve()} "
          f"({'found' if system_path.exists() else 'NOT FOUND'})")
    print(f"  package : {package_path.resolve() if package_path else '(none)'}")

    cache_dir, cache_src = resolve_with_source(
        system, package, "cache", "dir", str(DEFAULT_CACHE_DIR))
    tag, tag_src = resolve_with_source(
        system, package, "platform", "tag", default_tag())
    db_url, db_src = resolve_with_source(
        system, package, "database", "url", "(compose default)")
    compose_files, compose_src = resolve_with_source(
        system, package, "platform", "compose_files", DEFAULT_PLATFORM_COMPOSE_FILES)

    print("\nplatform")
    print(f"  marigold version : {package_version()}")
    print(f"  image tag        : {tag}  [{tag_src}]")
    print(f"  cache dir        : {cache_dir}  [{cache_src}]")
    print(f"  database url     : {db_url}  [{db_src}]")
    print(f"  compose files    : {compose_files}  [{compose_src}]")

    if package_dir is not None:
        merged = merge_config(system, package)
        _, image_src = resolve_with_source(
            system, package, "execution", "image", DEFAULT_EXECUTION_IMAGE)
        models_yaml, models_src = resolve_with_source(
            system, package, "package", "models_yaml", ["models.yaml"])
        package_name, package_ver = packages.package_identity(package_dir, merged)
        name = packages.application_name(package_dir, merged)

        print("\npackage")
        print(f"  name             : {package_name} {package_ver}")
        print(f"  root             : {package_dir}")
        print(f"  models yaml      : {models_yaml}  [{models_src}]")
        print(f"  compose files    : {platform_compose_files(merged)}")

        print("\napplication")
        print(f"  name             : {name}")
        print(f"  compose project  : {application_project(name)}")
        print(f"  image            : {execution_image(merged, tag)}  [{image_src}]")
        print(f"  command          : {execution_command(merged) or '(image default)'}")

    print("\ncache layout")
    for name, path in cache_paths(Path(cache_dir)).items():
        exists = "ok" if path.exists() else "missing"
        print(f"  {name:<13}: {path}  ({exists})")

    environment = {**system.get("environment", {}), **package.get("environment", {})}

    if environment:
        print("\nenvironment passthrough")
        for key, value in sorted(environment.items()):
            source = "package" if key in package.get("environment", {}) else "system"
            print(f"  {key} = {value}  [{source}]")

    sys.exit(0)


def _print_platform_config(config: dict, env: dict):
    path = system_config_path()
    found = "found" if path.exists() else "NOT FOUND -- using hardcoded defaults"

    print("marigold: platform configuration", file=sys.stderr)
    print(f"  system config    : {path} ({found})", file=sys.stderr)
    print(f"  marigold version : {package_version()}", file=sys.stderr)
    print(f"  image tag        : {env.get('TAG')}", file=sys.stderr)
    print(f"  compose files    : {platform_compose_files(config)}", file=sys.stderr)
    print(f"  cache dir        : {env.get('MARIGOLD_CACHE_DIR')}", file=sys.stderr)
    print(f"  database url     : {env.get('MARIGOLD_DATABASE_URL', '(compose default)')}", file=sys.stderr)


def _print_effective_config(package_dir: Path, config: dict, env: dict):
    """Print the current config to stderr.

    TODO: this should be a `config` command in its own right, not just
    a debug printout inside `start`.
    """
    _print_platform_config(config, env)

    print(f"  package root     : {package_dir}", file=sys.stderr)
    print(f"  application      : {env.get('MARIGOLD_APPLICATION_NAME')}", file=sys.stderr)
    print(f"  app project      : {application_project(env['MARIGOLD_APPLICATION_NAME'])}", file=sys.stderr)
    print(f"  app image        : {env.get('MARIGOLD_EXECUTION_IMAGE')}", file=sys.stderr)
    print(f"  app command      : {env.get('MARIGOLD_EXECUTION_COMMAND', '(image default)')}", file=sys.stderr)

    if "HF_TOKEN" in env:
        print("  HF_TOKEN         : from environment", file=sys.stderr)


# ---------------------------------------------------------------------------
# platform
# ---------------------------------------------------------------------------

def _start_platform(package_dir: Path | None, config: dict, env: dict) -> int:
    """Bring the platform up and wait for it to be healthy.

    Two passes: the first creates or recreates everything, the second
    waits. Starting a platform that is already up is a no-op, unless a
    package adds compose files the running platform does not have, in
    which case those services join it.
    """
    ensure_cache_layout(cache_dir_from_config(config))

    names = platform_compose_files(config)

    returncode = run_compose(
        package_dir, config, ["up", "-d", "--remove-orphans"],
        env=env, compose_file_names=names,
    )

    if returncode != 0:
        return returncode

    return run_compose(
        package_dir, config,
        ["up", "-d", "--wait", "--wait-timeout", "120"],
        env=env, compose_file_names=names,
    )


def cmd_platform_start(args):
    """Start the platform.

    With no target everything comes from the system config: the
    platform is a host concern and needs no package. A target adds that
    package's compose files, which is the path `application start`
    takes.
    """
    if args.target:
        package_dir, config, env = _package(args.target)
        _print_effective_config(package_dir, config, env)
    else:
        package_dir, config = None, load_system_config()
        env = platform_env(config)
        _print_platform_config(config, env)

    sys.exit(_start_platform(package_dir, config, env))


def cmd_platform_stop(args):
    """Stop the platform.

    Applications are left running unless --applications is given: they
    are separate projects, and several may share one platform. An
    application whose platform has gone keeps running and fails its API
    calls, which is visible in its logs.
    """
    returncode = 0

    if args.applications:
        for project in application_projects():
            print(f"marigold: stopping {project}", file=sys.stderr)
            returncode |= run_project_compose(project, ["down"])

    sys.exit(returncode | run_project_compose(PLATFORM_PROJECT, ["down"]))


def cmd_platform_status(args):
    # TODO: after printing ps, compare running image tags against the
    # resolved tag and print a line per service that differs
    returncode = run_project_compose(PLATFORM_PROJECT, ["ps", "-a"])

    for project in application_projects():
        print(f"\n{project}", file=sys.stderr)
        returncode |= run_project_compose(project, ["ps", "-a"])

    sys.exit(returncode)


def cmd_platform_logs(args):
    """Tail platform logs."""
    extra = ["logs"] if args.no_follow else ["logs", "-f"]

    if args.service:
        extra.append(args.service)

    sys.exit(run_project_compose(PLATFORM_PROJECT, extra))


# ---------------------------------------------------------------------------
# application
# ---------------------------------------------------------------------------

def _start_application(package_dir: Path, config: dict, env: dict) -> int:
    """Start this package's application containers.

    Every package runs in a container. What it runs is the package's
    business: a package with nothing to run says so through the
    container's own exit status, which `application status` and
    `application logs` report, rather than through the CLI inspecting
    the package's file layout.
    """
    name = env["MARIGOLD_APPLICATION_NAME"]
    outputs = Path(env["MARIGOLD_APPLICATIONS_DIR"]) / name / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)

    print(f"\nmarigold: starting application '{name}'", file=sys.stderr)

    return run_application_compose(
        package_dir, config, ["up", "-d", "--remove-orphans"], env=env
    )


def cmd_application_start(args):
    """Start the platform, then this package's application."""
    package_dir, config, env = _package(args.target)
    _print_effective_config(package_dir, config, env)

    returncode = _start_platform(package_dir, config, env)

    if returncode != 0:
        sys.exit(returncode)

    returncode = _start_application(package_dir, config, env)

    if returncode == 0:
        name = env["MARIGOLD_APPLICATION_NAME"]
        print(f"\nmarigold: application started ({name})")
        print(f"  marigold application logs {name}     -- follow application logs")
        print(f"  marigold application status {name}   -- check container state")
        print("  marigold platform logs               -- follow platform logs")

    sys.exit(returncode)


def cmd_application_stop(args):
    """Stop this package's application. The platform stays up.

    Several applications share one platform, so bringing it down
    belongs to `marigold platform stop`.
    """
    sys.exit(run_project_compose(_application_target(args.target), ["down"]))


def cmd_application_status(args):
    sys.exit(run_project_compose(_application_target(args.target), ["ps", "-a"]))


def cmd_application_logs(args):
    """Tail logs from this package's application."""
    extra = ["logs"] if args.no_follow else ["logs", "-f"]

    if args.service:
        extra.append(args.service)

    sys.exit(run_project_compose(_application_target(args.target), extra))


# ---------------------------------------------------------------------------
# cache
# ---------------------------------------------------------------------------

def cmd_cache_init(args):
    """Create the cache layout for this host."""
    cache_dir = cache_dir_from_system_config()
    paths = ensure_cache_layout(cache_dir)

    print(f"cache root: {cache_dir}")
    for name, path in paths.items():
        print(f"  {name:<13}: {path}")

    sys.exit(0)


def cmd_cache_validate(args):
    """Check a package's models.yaml files load cleanly.

    In-process, no container: models.catalogue has no eager side
    effects at import time, verified directly.
    """
    package_dir = packages.resolve_target(args.target)
    config = load_config(package_dir)

    items = packages.package_models(package_dir, config)

    for item in items:
        print(f"  {item.type.value:<16} {item.name}")

    print(f"\n{len(items)} models declared by {package_dir}")
    sys.exit(0)


def cmd_cache_populate(args):
    """Cache and register the models an installed package declares.

    The cache container mounts the applications directory and reads the
    package from there, so the package has to be installed. It reads
    the package's own marigold.toml: the CLI passes a path and nothing
    else.
    """
    package_dir, config, env = _package(args.target)
    cache_dir = cache_dir_from_config(config)
    ensure_cache_layout(cache_dir)

    package_in_container = container_path(package_dir, cache_dir)

    print(f"marigold: cache dir = {cache_dir}", file=sys.stderr)
    print(f"marigold: package   = {package_dir}", file=sys.stderr)
    print(f"marigold: image tag = {env['TAG']}", file=sys.stderr)

    command = [
        "python3", "-m", "tools.cache_cli", "populate",
        "--package", package_in_container,
    ]

    if args.prune:
        print("marigold: pruning models absent from this package", file=sys.stderr)
        command.append("--prune")

    sys.exit(run_compose(
        package_dir, config,
        ["run", "--rm", "cache-init", *command],
        env=env,
    ))


def _hf_cache_dirname_to_model_name(dirname: str) -> str:
    """'models--org--name' -> 'org/name', HuggingFace's own cache
    directory convention."""
    if dirname.startswith("models--"):
        parts = dirname[len("models--"):].split("--", 1)
        if len(parts) == 2:
            return f"{parts[0]}/{parts[1]}"
    return dirname


def cmd_cache_inspect(args):
    """List what is on disk, with sizes. Pure filesystem scan."""
    cache_dir = cache_dir_from_system_config()
    models_dir = cache_paths(cache_dir)["models"]

    if not models_dir.exists():
        print(f"cache dir  : {cache_dir}", file=sys.stderr)
        print(f"models dir does not exist: {models_dir}", file=sys.stderr)
        sys.exit(1)

    entries = []
    total_bytes = 0

    for child in sorted(models_dir.iterdir()):
        if not child.is_dir():
            continue
        size = cache_dir_bytes(child)
        total_bytes += size
        entries.append((_hf_cache_dirname_to_model_name(child.name), size))

    print(f"cache location: {models_dir}\n")
    for name, size in entries:
        print(f"  {name:<55} {size / 1e9:>8.2f} GB")
    print(f"\n{len(entries)} model(s), {total_bytes / 1e9:.2f} GB total")

    sys.exit(0)


def cmd_cache_stub(args):
    print(f"marigold cache {args.cache_command}: not yet implemented")
    sys.exit(1)


# ---------------------------------------------------------------------------
# package
# ---------------------------------------------------------------------------

def cmd_package_create(args):
    """Build a package archive from a package directory."""
    source = Path(args.target).resolve()
    config = load_toml(source / PACKAGE_CONFIG_NAME)

    for yaml_name in setting(config, "package", "models_yaml", ["models.yaml"]):
        if not (source / yaml_name).exists():
            print(f"marigold: warning: {yaml_name} declared but not present", file=sys.stderr)

    archive, count = packages.create_archive(source, Path(args.output).resolve())

    print(f"{archive}  ({count} files, {archive.stat().st_size / 1e6:.2f} MB)")
    sys.exit(0)


def cmd_package_install(args):
    """Install a package archive so it can be started by name."""
    archive = Path(args.archive).resolve()

    if not archive.is_file() or not packages.is_archive(args.archive):
        print(
            f"'{args.archive}' is not a package archive "
            f"({', '.join(packages.PACKAGE_ARCHIVE_SUFFIXES)})",
            file=sys.stderr,
        )
        sys.exit(1)

    name, package_ver, root, digest, previous = packages.install_archive(archive)

    if previous and previous["digest"] != digest:
        print(
            f"marigold: replaced {name} {previous['version']} "
            f"({previous['digest'][:12]})",
            file=sys.stderr,
        )

    print(f"installed {name} {package_ver}")
    print(f"  root : {root}")
    print(f"  run  : marigold application start {name}")
    sys.exit(0)


def cmd_package_list(args):
    """List installed packages."""
    index = packages.load_installed()

    if not index:
        print("no packages installed")
        sys.exit(0)

    for name in sorted(index):
        record = index[name]
        root = Path(record["root"])
        state = "ok" if (root / PACKAGE_CONFIG_NAME).exists() else "MISSING"
        print(f"  {name:<30} {record['version']:<12} {record['digest'][:12]}  {state}")

    print(f"\n{len(index)} package(s), index at {packages.installed_index_path()}")
    sys.exit(0)


def cmd_package_uninstall(args):
    """Remove an installed package."""
    record = packages.uninstall(args.name)

    print(f"uninstalled {args.name} {record['version']}")
    sys.exit(0)


def cmd_package_stub(args):
    print(f"marigold package {args.package_command}: not yet implemented")
    sys.exit(1)
