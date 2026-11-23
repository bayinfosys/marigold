"""Command implementations: the only layer that exits.

Everything below raises; these functions decide what a failure means
for the user and pick the exit code.
"""

import contextlib
import json
import os
import subprocess
import sys
import tempfile

from pathlib import Path

import httpx

from shared import model_cache

from cli import applications, archives, manifest, registries, registry
from cli.registry_config import REGISTRY_CONFIG_NAME, load_registry_config
from cli.compose import (
    DEFAULT_EXECUTION_IMAGE,
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
    APPLICATION_CONFIG_NAME,
    host_config_path,
    host_dict,
    host_keys_set,
    load_application_toml,
    load_config,
    load_host_config,
    load_platform_config,
    marigold_version,
    merge_config,
    setting,
)
from cli.host_config import HOST_CONFIG_ENV, HOST_CONFIG_NAME
from cli.paths import (
    cache_dir_from_config,
    cache_dir_from_system_config,
    cache_paths,
    container_path,
    ensure_cache_layout,
)


def _application(target: str) -> tuple[Path, dict, dict]:
    """(root, merged config, compose environment) for one target."""
    application_dir = applications.resolve_target(target)
    config = load_config(application_dir)

    return application_dir, config, compose_env(application_dir, config)


def _application_target(target: str) -> str:
    """The compose project for a target, for commands that only need one.

    Resolving the application gives the application name. When the
    application has been uninstalled and its containers are still there,
    a target that looks like an application name is taken as one, so
    they can still be stopped and inspected.
    """
    try:
        _, _, env = _application(target)
        return application_project(env["MARIGOLD_APPLICATION_NAME"])
    except FileNotFoundError:
        if not applications.NAME_RE.match(target):
            raise

        project = application_project(target)

        if project not in application_projects():
            raise

        return project


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------

def _host_config_source(path: Path | None) -> str:
    if path is None:
        return "none found: every value is a default"
    if os.environ.get(HOST_CONFIG_ENV):
        return f"{HOST_CONFIG_ENV} or --host-config"
    if path.parent.resolve() == Path.cwd().resolve():
        return "current directory"
    return "home directory"


def cmd_config_path(args):
    """Print the host config file in use, absolute."""
    path = host_config_path()

    if path is None:
        print(f"no {HOST_CONFIG_NAME} found: every value is a default")
        sys.exit(1)

    print(f"{path.resolve()}  ({_host_config_source(path)})")
    sys.exit(0)


def cmd_config_show(args):
    """Print the resolved host config, and an application's if given.

    Each host value is marked [host] when marigold-host.toml sets it and
    [default] otherwise; application values are marked [application].
    """
    path = host_config_path()
    host = load_host_config(path)
    set_keys = host_keys_set(path)

    print("sources")
    print(f"  host        : {path.resolve() if path else '(none)'}  ({_host_config_source(path)})")

    for section, values in host_dict(host).items():
        if section == "environment":
            continue

        if section == "registry":
            source = "host" if set_keys.get("registry") else "default"
            print(f"\n[[registry]]  [{source}]")
            for position, entry in enumerate(values, start=1):
                label = f" ({entry['name']})" if entry.get("name") else ""
                print(f"  {position}. {entry['url']}{label}")
            if not values:
                print("  (none)")
            continue

        print(f"\n[{section}]")
        for key, value in values.items():
            source = "host" if key in set_keys.get(section, set()) else "default"
            print(f"  {key:<14}: {value}  [{source}]")

    print(f"\n  marigold version : {marigold_version()}")

    application: dict = {}

    if args.target is not None:
        application_dir = applications.resolve_target(args.target)
        candidate = application_dir / APPLICATION_CONFIG_NAME
        application = load_application_toml(candidate) if candidate.exists() else {}
        merged = merge_config(host_dict(host), application)
        tag = host.platform.tag or default_tag()
        app_name = applications.declared_name(application_dir, merged)
        run_name = applications.application_name(application_dir, merged)
        _, app_digest = manifest.application_manifest(application_dir)

        print("\napplication")
        print(f"  config           : {candidate if candidate.exists() else '(none)'}")
        print(f"  name             : {app_name}")
        print(f"  digest           : {manifest.short(app_digest)}")
        print(f"  root             : {application_dir}")
        print(f"  models yaml      : {setting(merged, 'application', 'models_yaml', ['models.yaml'])}")
        print(f"  compose files    : {platform_compose_files(merged)}")
        print(f"  compose project  : {application_project(run_name)}")
        print(f"  image            : {execution_image(merged, tag)}")
        print(f"  command          : {execution_command(merged) or '(image default)'}")

    print("\ncache layout")
    for name, cache_path in cache_paths(host.storage.location).items():
        exists = "ok" if cache_path.exists() else "missing"
        print(f"  {name:<13}: {cache_path}  ({exists})")

    environment = {**host.environment, **application.get("environment", {})}

    if environment:
        print("\nenvironment passthrough")
        for key, value in sorted(environment.items()):
            source = "application" if key in application.get("environment", {}) else "host"
            print(f"  {key} = {value}  [{source}]")

    sys.exit(0)


def _print_platform_config(config: dict, env: dict):
    path = host_config_path()

    print("marigold: platform configuration", file=sys.stderr)
    print(f"  host config      : {path.resolve() if path else '(none: defaults)'}", file=sys.stderr)
    print(f"  marigold version : {marigold_version()}", file=sys.stderr)
    print(f"  image tag        : {env.get('TAG')}", file=sys.stderr)
    print(f"  compose files    : {platform_compose_files(config)}", file=sys.stderr)
    print(f"  cache dir        : {env.get('MARIGOLD_CACHE_DIR')}", file=sys.stderr)
    print(f"  api              : {env.get('MARIGOLD_BIND')}:{env.get('MARIGOLD_API_PORT')}", file=sys.stderr)


def _print_effective_config(application_dir: Path, config: dict, env: dict):
    """Print the current config to stderr.

    TODO: this should be a `config` command in its own right, not just
    a debug printout inside `start`.
    """
    _print_platform_config(config, env)

    name = env["MARIGOLD_APPLICATION_NAME"]

    print(f"  application root : {application_dir}", file=sys.stderr)
    print(f"  application name : {name}", file=sys.stderr)
    print(f"  compose project  : {application_project(name)}", file=sys.stderr)
    print(f"  image            : {env.get('MARIGOLD_EXECUTION_IMAGE')}", file=sys.stderr)
    print(f"  command          : {env.get('MARIGOLD_EXECUTION_COMMAND', '(image default)')}", file=sys.stderr)

    if "HF_TOKEN" in env:
        print("  HF_TOKEN         : from environment", file=sys.stderr)


# ---------------------------------------------------------------------------
# platform
# ---------------------------------------------------------------------------

def _start_platform(application_dir: Path | None, config: dict, env: dict) -> int:
    """Bring the platform up and wait for it to be healthy.

    Two passes: the first creates or recreates everything, the second
    waits. Starting a platform that is already up is a no-op, unless an
    application adds compose files the running platform does not have,
    in which case those services join it.
    """
    ensure_cache_layout(cache_dir_from_config(config))

    names = platform_compose_files(config)

    returncode = run_compose(
        application_dir, config, ["up", "-d", "--remove-orphans"],
        env=env, compose_file_names=names,
    )

    if returncode != 0:
        return returncode

    return run_compose(
        application_dir, config,
        ["up", "-d", "--wait", "--wait-timeout", "120"],
        env=env, compose_file_names=names,
    )


def cmd_platform_start(args):
    """Start the platform.

    With no target everything comes from marigold-host.toml: the
    platform is a host concern and needs no application. A target adds
    that application's compose files, which is the path
    `application start` takes.
    """
    if args.target:
        application_dir, config, env = _application(args.target)
        _print_effective_config(application_dir, config, env)
    else:
        application_dir, config = None, load_platform_config()
        env = platform_env(config)
        _print_platform_config(config, env)

    sys.exit(_start_platform(application_dir, config, env))


def cmd_platform_stop(args):
    """Stop every application, then the platform.

    Each application's containers join the applications network, which
    the platform's compose project creates and removes. Bringing the
    applications down first means the network is never removed beneath
    a stopped container, which would then fail to start.
    """
    returncode = 0

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
# application: runtime
# ---------------------------------------------------------------------------

def _start_application(application_dir: Path, config: dict, env: dict) -> int:
    """Start this application's containers.

    Every application runs in a container. What it runs is the
    application's business: an application with nothing to run says so
    through the container's own exit status, reported by
    `application status` and `application logs`.
    """
    name = env["MARIGOLD_APPLICATION_NAME"]
    outputs = Path(env["MARIGOLD_APPLICATIONS_DIR"]) / name / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)

    print(f"\nmarigold: starting application '{name}'", file=sys.stderr)

    return run_application_compose(
        application_dir, config, ["up", "-d", "--remove-orphans"], env=env
    )


def cmd_application_start(args):
    """Start the platform, then this application."""
    application_dir, config, env = _application(args.target)
    _print_effective_config(application_dir, config, env)

    returncode = _start_platform(application_dir, config, env)

    if returncode != 0:
        sys.exit(returncode)

    returncode = _start_application(application_dir, config, env)

    if returncode == 0:
        name = env["MARIGOLD_APPLICATION_NAME"]
        print(f"\nmarigold: application started ({name})")
        print(f"  marigold application logs {name}     -- follow application logs")
        print(f"  marigold application status {name}   -- check container state")
        print("  marigold platform logs               -- follow platform logs")

    sys.exit(returncode)


def cmd_application_stop(args):
    """Stop this application. The platform stays up.

    Several applications share one platform, so bringing it down
    belongs to `marigold platform stop`.
    """
    sys.exit(run_project_compose(_application_target(args.target), ["down"]))


def cmd_application_status(args):
    sys.exit(run_project_compose(_application_target(args.target), ["ps", "-a"]))


def cmd_application_logs(args):
    """Tail logs from this application."""
    extra = ["logs"] if args.no_follow else ["logs", "-f"]

    if args.service:
        extra.append(args.service)

    sys.exit(run_project_compose(_application_target(args.target), extra))


# ---------------------------------------------------------------------------
# application: build and install
# ---------------------------------------------------------------------------

def cmd_application_create(args):
    """Build an application archive from an application directory."""
    source = Path(args.target).resolve()
    config_path = source / APPLICATION_CONFIG_NAME

    if not config_path.exists():
        raise FileNotFoundError(f"no {APPLICATION_CONFIG_NAME} in {source}")

    config = load_application_toml(config_path)

    for yaml_name in setting(config, "application", "models_yaml", ["models.yaml"]):
        if not (source / yaml_name).exists():
            print(f"marigold: warning: {yaml_name} declared but not present", file=sys.stderr)

    archive, count, digest = applications.build_archive(
        source, Path(args.output).resolve(), args.version
    )

    print(f"{archive}  ({count} files, {archive.stat().st_size / 1e6:.2f} MB)")
    print(f"  digest : {manifest.short(digest)}")
    sys.exit(0)


def cmd_application_install(args):
    """Install an application: an archive file, or a name from a registry.

    A target that is a file is installed as an archive. Anything else is
    a name, or name@version, looked up in the [[registry]] entries of
    marigold-host.toml, in order.
    """
    path = Path(args.target)

    if path.is_file():
        if not archives.is_archive(args.target):
            raise ValueError(
                f"'{args.target}' is not an application archive "
                f"({', '.join(archives.ARCHIVE_SUFFIXES)})"
            )
        name, root, record, previous = applications.install(path.resolve(), args.version)
    else:
        with registries.temporary_directory() as tmp:
            archive, url, version, entry = registries.fetch(
                args.target, load_host_config().registry, Path(tmp)
            )
            print(f"marigold: {Path(entry['archive']).name} from {url}", file=sys.stderr)
            name, root, record, previous = applications.install(
                archive, version, expected_manifest=entry["digest"], registry=url
            )


    if previous and previous.get("manifest") != record["manifest"]:
        print(
            f"marigold: replaced {name} {previous['version']} "
            f"({manifest.short(previous.get('manifest', ''))})",
            file=sys.stderr,
        )

    print(f"installed {name} {record['version']}")
    if record.get("registry"):
        print(f"  from   : {record['registry']}")
    print(f"  digest : {manifest.short(record['manifest'])}")
    print(f"  root   : {root}")
    print(f"  run    : marigold application start {name}")
    sys.exit(0)


def cmd_application_list(args):
    """List installed applications."""
    index = applications.load_installed()

    if not index:
        print("no applications installed")
        sys.exit(0)

    for name in sorted(index):
        record = index[name]
        root = Path(record["root"])
        state = "ok" if (root / APPLICATION_CONFIG_NAME).exists() else "MISSING"
        source = record.get("registry") or "local"
        print(f"  {name:<30} {record['version']:<12} {manifest.short(record.get('manifest', '-')):<12}  {state:<8} {source}")

    print(f"\n{len(index)} application(s), index at {applications.installed_index_path()}")
    sys.exit(0)


def cmd_application_verify(args):
    """Check installed applications' files against their recorded digests.

    One line per application: the named one, or with no name every
    installed application. Exits 1 when any has changed, for use from
    cron or CI.
    """
    names = [args.name] if args.name else sorted(applications.load_installed())
    changed = 0

    for name in names:
        record, digest = applications.verify(name)

        if digest == record["manifest"]:
            print(f"{name} {record['version']}: ok ({manifest.short(digest)})")
            continue

        changed += 1
        print(
            f"{name} {record['version']}: files changed since install "
            f"(recorded {manifest.short(record['manifest'])}, now {manifest.short(digest)})"
        )

    sys.exit(1 if changed else 0)


def _diff_side(target: str, stack: contextlib.ExitStack) -> tuple[str, Path]:
    """(label, application directory) for one side of a diff.

    An installed name, an application directory, or an archive, which
    is extracted to a temporary directory for the length of the diff.
    """
    path = Path(target)

    if archives.is_archive(target) and path.is_file():
        tmp = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        return target, archives.extract_to(path.resolve(), tmp)

    return target, applications.resolve_target(target)


def cmd_application_diff(args):
    """Compare two applications file by file, through their manifests."""
    with contextlib.ExitStack() as stack:
        (label_a, root_a), (label_b, root_b) = (
            _diff_side(args.old, stack),
            _diff_side(args.new, stack),
        )
        text_a, digest_a = manifest.application_manifest(root_a)
        text_b, digest_b = manifest.application_manifest(root_b)

        print(f"--- {label_a}  {manifest.short(digest_a)}")
        print(f"+++ {label_b}  {manifest.short(digest_b)}")

        if digest_a == digest_b:
            print("identical")
            sys.exit(0)

        changes = manifest.compare(text_a, text_b)

        for mark, key in (("A", "added"), ("D", "removed"), ("M", "changed")):
            for path in changes[key]:
                print(f"{mark}  {path}")

        if args.content:
            for path in changes["changed"]:
                sys.stdout.flush()
                subprocess.run([
                    "diff", "-u",
                    "--label", f"{label_a}/{path}", "--label", f"{label_b}/{path}",
                    str(root_a / path), str(root_b / path),
                ])

    sys.exit(1)


def cmd_application_uninstall(args):
    """Remove an installed application. The cache and catalogue are untouched."""
    record = applications.uninstall(args.name)

    print(f"uninstalled {args.name} {record['version']}")
    sys.exit(0)


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
    """Check an application's models.yaml files load cleanly.

    In-process, no container: shared.catalogue has no eager side
    effects at import time, verified directly.
    """
    application_dir = applications.resolve_target(args.target)
    config = load_config(application_dir)

    items = applications.application_models(application_dir, config)

    for item in items:
        print(f"  {item.type.value:<16} {item.name}")

    print(f"\n{len(items)} models declared by {application_dir}")
    sys.exit(0)


def cmd_cache_populate(args):
    """Cache and register the models an installed application declares.

    The cache container mounts the applications directory and reads the
    application from there, so the application has to be installed. It
    reads the application's marigold.toml: the CLI passes a path and
    nothing else.
    """
    application_dir, config, env = _application(args.target)
    cache_dir = cache_dir_from_config(config)
    ensure_cache_layout(cache_dir)

    application_in_container = container_path(application_dir, cache_dir)

    print(f"marigold: cache dir   = {cache_dir}", file=sys.stderr)
    print(f"marigold: application = {application_dir}", file=sys.stderr)
    print(f"marigold: image tag   = {env['TAG']}", file=sys.stderr)

    command = [
        "python3", "-m", "tools.cache_cli", "populate",
        "--application", application_in_container,
    ]

    if args.prune:
        print("marigold: pruning models absent from this application", file=sys.stderr)
        command.append("--prune")

    sys.exit(run_compose(
        application_dir, config,
        ["run", "--rm", "cache-init", *command],
        env=env,
    ))


def _models_dir() -> Path:
    """The model cache directory, which must exist."""
    models_dir = cache_paths(cache_dir_from_system_config())["models"]

    if not models_dir.is_dir():
        raise FileNotFoundError(f"no model cache at {models_dir}; run marigold cache init")

    return models_dir


def cmd_cache_list(args):
    """Cached model names, one per line."""
    for name in model_cache.cached_models(_models_dir()):
        print(name)

    sys.exit(0)


def cmd_cache_inspect(args):
    """Size, revision and file count per cached model, and the total.

    Sizes follow links into the shared blob store, so each model shows
    its full size; the total counts every file under the cache once.
    """
    models_dir = _models_dir()
    models = model_cache.cached_models(models_dir)

    if args.name is not None:
        if args.name not in models:
            raise FileNotFoundError(f"'{args.name}' is not in the cache at {models_dir}")
        models = {args.name: models[args.name]}

    print(f"cache location: {models_dir}\n")
    print(f"  {'model':<55} {'GB':>8}  {'revision':<12}  files")

    for name, path in models.items():
        size = model_cache.model_bytes(name, models_dir) / model_cache.GB
        revision = (model_cache.model_revision(name, models_dir) or "-")[:12]
        files = model_cache.model_files(name, models_dir)
        print(f"  {name:<55} {size:>8.2f}  {revision:<12}  {files}")
        if args.name is not None:
            print(f"\n  {path}")

    if args.name is None:
        total = model_cache.files_bytes(models_dir) / model_cache.GB
        print(f"\n{len(models)} model(s), {total:.2f} GB on disk")

    sys.exit(0)


def cmd_cache_stub(args):
    print(f"marigold cache {args.cache_command}: not yet implemented")
    sys.exit(1)


# ---------------------------------------------------------------------------
# models
# ---------------------------------------------------------------------------

def _api_get(base: str, path: str):
    response = httpx.get(f"{base}{path}", timeout=10)
    response.raise_for_status()
    return response.json()


def _model_applications(source_file: str) -> str:
    """The installed applications whose models.yaml declared a model.

    source_file is the models.yaml path as the cache container read it,
    under the application's extracted tree, which is named by its digest
    on the host as in the container. An application installed
    elsewhere, as on a remote platform, shows as that directory.
    """
    directory = Path(source_file).parent

    names = sorted(
        name for name, record in applications.load_installed().items()
        if Path(record["root"]).name == directory.name
    )

    return ", ".join(names) or str(directory)


def _gb(value: int) -> str:
    return f"{value / 1e9:.2f} GB"


def _print_model(model: dict) -> None:
    """One model: status, settings with sources, last load, usage, recent events."""
    print(f"{model['name']} ({model['type']})")
    print(f"  application : {_model_applications(model['source_file'])}")
    print(f"  status      : {'failed' if model['failed_reason'] else 'ok'}")
    if model["failed_reason"]:
        print(f"  reason      : {model['failed_reason']}")

    print("\nsettings")
    for name, setting in sorted(model["settings"].items()):
        print(f"  {name:<28} {json.dumps(setting['value']):<12} [{setting['source']}]")

    events = model["events"]
    loads = [e for e in events if e["event_type"] in ("MODEL_LOADED", "MODEL_LOAD_FAILED")]

    print("\nlast load")
    if loads:
        load = loads[0]
        payload = load["payload"]
        print(f"  {load['timestamp']}  {load['event_type']}  on {payload.get('worker_id', '-')}")
        if "footprint_bytes" in payload:
            print(f"  footprint : {_gb(payload['footprint_bytes'])}  dtype: {payload.get('dtype') or '-'}")
        if "placement" in payload:
            print("  placement : " + ", ".join(f"{d} {_gb(n)}" for d, n in sorted(payload["placement"].items())))
        if "error" in payload:
            print(f"  error     : {payload['error']}")
    else:
        print(f"  none in the {len(events)} most recent events")

    usage = model["usage"]

    print("\nusage")
    if usage["requests"]:
        duration = usage["duration_ms"]
        print(f"  requests  : {usage['requests']}")
        print(f"  tokens    : {usage['input_tokens']} in, {usage['output_tokens']} out")
        print(f"  duration  : p50 {duration['p50'] / 1000:.2f}s  p90 {duration['p90'] / 1000:.2f}s  p99 {duration['p99'] / 1000:.2f}s")
        print(f"  load time : {usage['load_time_ms_mean'] / 1000:.1f}s mean")
        print(f"  peak VRAM : {_gb(usage['vram_bytes_peak'])}")
        print(f"  power     : {usage['power_watts_mean']:.0f} W mean, {usage['power_watts_peak']:.0f} W peak")
    else:
        print("  none recorded")

    print("\nrecent events")
    for event in reversed(events):
        detail = event["message_id"] or ""
        if "error" in event["payload"]:
            detail = f"{detail} {event['payload']['error']}".strip()
        print(f"  {event['timestamp']}  {event['event_type']:<20} {detail}")
    if not events:
        print("  (none)")


def cmd_models_inspect(args):
    """The catalogue, or one model, from the API at the configured address.

    With no name, each model's name, type, application and status. With
    a name, its settings and their sources, its status and failure
    reason, its last load, a summary of its usage and its recent events.
    """
    base = load_host_config().api_url()
    catalogue = _api_get(base, "/models")

    if args.name is None:
        print(f"  {'model':<50} {'type':<16} {'status':<8} application")
        for model in sorted(catalogue, key=lambda m: (m["name"], m["type"])):
            status = "failed" if model["failed_reason"] else "ok"
            print(f"  {model['name']:<50} {model['type']:<16} {status:<8} {_model_applications(model['source_file'])}")
        print(f"\n{len(catalogue)} model(s) at {base}")
        sys.exit(0)

    matches = [m for m in catalogue if m["name"] == args.name]

    if not matches:
        raise LookupError(f"no model named '{args.name}' in the catalogue at {base}")

    for position, match in enumerate(matches):
        if position:
            print()
        _print_model(_api_get(base, f"/models/{match['type']}/{match['name']}"))

    sys.exit(0)


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------

def cmd_registry_add(args):
    """Append a registry to marigold-host.toml: registry add [NAME] URL."""
    if len(args.args) == 1:
        name, url = None, args.args[0]
    elif len(args.args) == 2:
        name, url = args.args
    else:
        raise ValueError("usage: marigold registry add [NAME] URL")

    path, entry = registries.add(url, name)
    label = f" ({entry.name})" if entry.name else ""
    print(f"added {entry.url}{label} to {path}")
    sys.exit(0)


def cmd_registry_list(args):
    """The registries, in the order they are searched."""
    entries = load_host_config().registry

    if not entries:
        print("no registries; marigold registry add [NAME] URL", file=sys.stderr)

    for position, entry in enumerate(entries, start=1):
        label = f"  ({entry.name})" if entry.name else ""
        print(f"{position}. {entry.url}{label}")

    sys.exit(0)


def cmd_registry_remove(args):
    """Remove a registry by name or url."""
    path, removed = registries.remove(args.key)
    print(f"removed {removed['url']} from {path}")
    sys.exit(0)


def cmd_registry_build(args):
    """Build a static registry from every application under a root.

    The root's marigold-registry.toml is required and supplies the
    registry's title, description and links, and optionally its site
    template and visitor text. Paths in it are relative to the root.
    """
    root = Path(args.root).resolve()
    section = load_registry_config(root / REGISTRY_CONFIG_NAME).registry

    def from_root(value: str | None) -> Path | None:
        return root / value if value else None

    front_page = Path(args.front_page) if args.front_page else from_root(section.front_page)
    site = Path(args.site) if args.site else from_root(section.site)
    out = Path(args.out) if args.out else root / "dist"

    if front_page is not None and not front_page.is_file():
        raise FileNotFoundError(f"front page not found: {front_page}")

    index, warnings = registry.build(
        root,
        out,
        version=args.version,
        title=section.title,
        description=section.description,
        urls=section.urls,
        front_page=front_page,
        site=site,
    )

    for warning in warnings:
        print(f"marigold: warning: {warning}", file=sys.stderr)

    count = 0

    for name, application in sorted(index["applications"].items()):
        for version, entry in sorted(application["versions"].items()):
            print(f"  {name:<30} {version:<12} {manifest.short(entry['digest'])}")
            count += 1

    print(f"\n{count} application(s), index at {out.resolve() / registry.INDEX_NAME}")
    sys.exit(0)
