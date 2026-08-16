"""marigold -- CLI for running a Marigold deployment.

marigold deployment start/stop/logs/status wraps docker compose against
the compose files packaged under compose/, reading two layers of TOML
config: a system-level config (config.toml in the current directory,
~/.marigold/config.toml, or $MARIGOLD_CONFIG) providing host defaults --
cache location, database URL, eventually repository list -- and a
package-level marigold.toml in the deployment directory itself,
declaring what the package needs (which compose files, which
models.yaml files, any environment variables other services in the
stack need). Package-level values override system-level ones; anything
neither sets falls back to a hardcoded default.

marigold cache manages the shared model cache directly, independent of
any deployment:
    validate  -- check one or more models.yaml files load cleanly.
                 In-process (imports models.catalogue.load_catalogue_from_yaml
                 directly -- safe: no torch, no network, no DB connection
                 at import time, verified before this was written).
    populate  -- download what's missing, prune what's unwanted (opt-in).
                 Runs cache-init via docker compose run.
    inspect   -- list what's on disk, sizes, location. Pure filesystem
                 scan, no container needed.
    seed      -- share cached models over torrent. STUB, not implemented.

marigold package is a stub. Repository resolution, manifest format,
signing, and publishing aren't designed yet -- see PACKAGES.md.

This CLI never runs a model or touches torch. cache validate/populate
import models.catalogue for schema validation only -- that module's
import chain was checked directly to confirm it has no eager side
effects (no DB connection, no network call) at import time.
"""

import argparse
import logging
import os
import subprocess
import sys
import tempfile
import tomllib
from importlib.metadata import PackageNotFoundError, version
from importlib.resources import files
from pathlib import Path

import yaml

PACKAGE_CONFIG_NAME = "marigold.toml"
SYSTEM_CONFIG_NAME = "config.toml"
DEFAULT_SYSTEM_CONFIG_PATH = Path.home() / ".marigold" / "config.toml"
DEFAULT_CACHE_DIR = Path.home() / ".marigold" / "cache"

COMPOSE_FILES = {
    "core": "docker-compose.core.yaml",
    "webui": "docker-compose.webui.yaml",
}


# ---------------------------------------------------------------------------
# version
# ---------------------------------------------------------------------------

def _package_version() -> str:
    try:
        return version("bayis-marigold")
    except PackageNotFoundError:
        return "0.0.0-dev"


# ---------------------------------------------------------------------------
# config loading -- system layer + package layer, package wins
# ---------------------------------------------------------------------------

def _system_config_path() -> Path:
    override = os.environ.get("MARIGOLD_CONFIG")
    if override:
        path = Path(override)
        if not path.exists():
            print(f"MARIGOLD_CONFIG set to '{path}', but it doesn't exist", file=sys.stderr)
            sys.exit(1)
        return path

    cwd_config = Path(SYSTEM_CONFIG_NAME)
    if cwd_config.exists():
        return cwd_config

    return DEFAULT_SYSTEM_CONFIG_PATH


def _load_toml(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


def _merge_config(system: dict, package: dict) -> dict:
    """Shallow-merge each top-level section; package values win per key.

    [environment] merges the same way -- a package can set one variable
    without needing to repeat any others the system config already set.
    """
    merged: dict = {}
    for section in set(system) | set(package):
        sys_section = system.get(section, {})
        pkg_section = package.get(section, {})
        if isinstance(sys_section, dict) and isinstance(pkg_section, dict):
            merged[section] = {**sys_section, **pkg_section}
        else:
            merged[section] = pkg_section if section in package else sys_section
    return merged


def _load_config(deployment_dir: Path) -> dict:
    package_config_path = deployment_dir / PACKAGE_CONFIG_NAME
    if not package_config_path.exists():
        print(
            f"no {PACKAGE_CONFIG_NAME} found in {deployment_dir} "
            "-- doesn't look like a marigold package",
            file=sys.stderr,
        )
        sys.exit(1)

    system_config = _load_toml(_system_config_path())
    package_config = _load_toml(package_config_path)
    return _merge_config(system_config, package_config)


def _cache_dir_from_system_config() -> Path:
    system_config = _load_toml(_system_config_path())
    return Path(system_config.get("cache", {}).get("dir", str(DEFAULT_CACHE_DIR)))


# ---------------------------------------------------------------------------
# deployment target resolution
# ---------------------------------------------------------------------------

def _resolve_deployment_target(target: str) -> Path:
    """Resolve a deployment target to a local directory.

    target is either a filesystem path, or a namespaced package
    reference '<host>.<package_name>' (e.g. 'bayinfosys.simple-rag').

    Namespaced references are meant to resolve by: checking whether
    the package already exists locally (previously fetched), then
    querying each repository in the system config's [repositories]
    list, in order, until one has it.

    STUB: repository resolution is not implemented -- no manifest
    format, no repository protocol, no local install location decided
    yet. See PACKAGES.md. Only plain filesystem paths work today.
    """
    path = Path(target)
    if path.exists():
        return path.resolve()

    if "." in target and not path.suffix:
        raise NotImplementedError(
            f"'{target}' looks like a namespaced package reference "
            "(<host>.<package_name>), but package repository "
            "resolution isn't implemented yet. Pass a filesystem "
            "path instead."
        )

    raise FileNotFoundError(f"deployment directory not found: {target}")


# ---------------------------------------------------------------------------
# compose invocation
# ---------------------------------------------------------------------------

def _compose_base_cmd(compose_file_names: list[str], project_directory: Path | None = None) -> list[str]:
    compose_dir = files("compose")
    cmd = ["docker", "compose", "-p", "marigold"]
    if project_directory is not None:
        cmd += ["--project-directory", str(project_directory)]
    for name in compose_file_names:
        filename = COMPOSE_FILES.get(name)
        if filename is None:
            print(f"unknown compose file '{name}'", file=sys.stderr)
            sys.exit(1)
        cmd += ["-f", str(compose_dir / filename)]
    return cmd


def _models_catalogue_yamls(config: dict) -> str:
    """Build MARIGOLD_MODEL_CATALOGUE_YAMLS from [deployment].models_yaml.

    Paths are relative to the package directory, which is always
    mounted at /app/marigold -- see MARIGOLD_PACKAGE_DIR. Comma-joined,
    matching ModelCatalogueContext.load()'s own parsing
    (yaml_patterns.split(",")), which already supports multiple files.
    """
    names = config.get("deployment", {}).get("models_yaml", ["models.yaml"])
    return ",".join(f"/app/marigold/{name}" for name in names)


def _compose_env(deployment_dir: Path, config: dict) -> dict:
    env = dict(os.environ)

    env["TAG"] = config.get("deployment", {}).get("tag", _package_version())

    env["MARIGOLD_PACKAGE_DIR"] = str(deployment_dir)
    env["MARIGOLD_MODEL_CATALOGUE_YAMLS"] = _models_catalogue_yamls(config)

    # Cache location is a host/system concern, not a package one.
    # config is already the merged system+package result, so this is
    # just: use whatever it resolved to, or a hardcoded last resort if
    # neither layer set one at all (e.g. no system config written yet).
    cache_dir = config.get("cache", {}).get("dir", str(DEFAULT_CACHE_DIR))
    env["MARIGOLD_CACHE_DIR"] = cache_dir

    # Same principle for database.url -- only set it if some config
    # layer explicitly provided one. Left unset otherwise, so
    # docker-compose.core.yaml's own fallback
    # (postgresql://marigold:marigold@postgres:5432/marigold) applies,
    # rather than duplicating that default here.
    db_url = config.get("database", {}).get("url")
    if db_url:
        env["MARIGOLD_DATABASE_URL"] = db_url

    # Package-declared variables for services other than api/worker/cache
    # -- e.g. RAG_EMBEDDING_MODEL for open-webui. The CLI doesn't know or
    # care what these mean; it just forwards them.
    for key, value in config.get("environment", {}).items():
        env[str(key)] = str(value)

    return env


def _run_compose(deployment_dir: Path, config: dict, extra_args: list[str], env: dict | None = None) -> int:
    if env is None:
        env = _compose_env(deployment_dir, config)
    names = config.get("deployment", {}).get("compose_files", ["core"])
    cmd = _compose_base_cmd(names, project_directory=deployment_dir) + extra_args
    result = subprocess.run(cmd, env=env)
    return result.returncode


# ---------------------------------------------------------------------------
# output the current configuration
# ---------------------------------------------------------------------------

def _print_effective_config(deployment_dir: Path, config: dict, env: dict):
    """Print the current config to stderr.

    TODO: this should be a `config` command in its own right, not just
    a debug printout inside `start` -- and `config` should also grow
    `new`/`set`/etc for manipulating it directly.
    """
    system_path = _system_config_path()
    found = "found" if system_path.exists() else "NOT FOUND -- using hardcoded defaults"
    print("marigold: effective configuration", file=sys.stderr)
    print(f"  package dir      : {deployment_dir}", file=sys.stderr)
    print(f"  system config    : {system_path} ({found})", file=sys.stderr)
    print(f"  compose files    : {config.get('deployment', {}).get('compose_files', ['core'])}", file=sys.stderr)
    print(f"  cache dir        : {env.get('MARIGOLD_CACHE_DIR')}", file=sys.stderr)
    print(f"  database url     : {env.get('MARIGOLD_DATABASE_URL', '(compose default)')}", file=sys.stderr)
    print(f"  models catalogue : {env.get('MARIGOLD_MODEL_CATALOGUE_YAMLS')}", file=sys.stderr)


# ---------------------------------------------------------------------------
# deployment subcommands
# ---------------------------------------------------------------------------

def cmd_deployment_start(args):
    deployment_dir = _resolve_deployment_target(args.target)
    config = _load_config(deployment_dir)
    env = _compose_env(deployment_dir, config)
    _print_effective_config(deployment_dir, config, env)

    returncode = _run_compose(deployment_dir, config, ["up", "-d", "--remove-orphans"], env=env)
    if returncode != 0:
        sys.exit(returncode)

    print("marigold: waiting on cache-init (first run may download models -- this can take a while)")
    _run_compose(deployment_dir, config, ["logs", "-f", "cache-init"], env=env)

    returncode = _run_compose(
        deployment_dir, config,
        ["up", "-d", "--wait", "--wait-timeout", "120"],
        env=env,
    )
    if returncode == 0:
        print(f"\nmarigold: deployment started ({deployment_dir})")
        print("  marigold deployment logs   -- follow logs")
        print("  marigold deployment status -- check container state")
    sys.exit(returncode)


def cmd_deployment_stop(args):
    deployment_dir = _resolve_deployment_target(args.target)
    config = _load_config(deployment_dir)
    sys.exit(_run_compose(deployment_dir, config, ["down"]))


def cmd_deployment_status(args):
    deployment_dir = _resolve_deployment_target(args.target)
    config = _load_config(deployment_dir)
    sys.exit(_run_compose(deployment_dir, config, ["ps"]))


def cmd_deployment_logs(args):
    deployment_dir = _resolve_deployment_target(args.target)
    config = _load_config(deployment_dir)
    extra = ["logs"] if args.no_follow else ["logs", "-f"]
    if args.service:
        extra.append(args.service)
    sys.exit(_run_compose(deployment_dir, config, extra))


# ---------------------------------------------------------------------------
# cache subcommands -- operate on the shared model cache directly,
# independent of any deployment
# ---------------------------------------------------------------------------

def _resolve_models_yaml_paths(raw_paths: list[str]) -> list[Path]:
    paths = []
    for path_str in raw_paths:
        p = Path(path_str).resolve()
        if not p.exists():
            print(f"models.yaml not found: {p}", file=sys.stderr)
            sys.exit(1)
        paths.append(p)
    return paths


def cmd_cache_validate(args):
    from models.catalogue import load_catalogue_from_yaml

    paths = _resolve_models_yaml_paths(args.models_yaml)
    items = load_catalogue_from_yaml([str(p) for p in paths])

    print(f"\n{len(items)} model(s) valid across {len(paths)} file(s):")
    for item in items:
        print(f"  {item.type.value}/{item.name}")

    # load_catalogue_from_yaml logs (via the `logging` module, now
    # configured in main()) any entry that failed validation or was
    # duplicated -- those already printed above this summary, to stderr.
    sys.exit(0)


def _stitch_models_yaml(paths: list[Path]) -> str:
    """Concatenate multiple models.yaml files' `models:` lists into one
    temporary file, returning its path.

    Structural only -- reads the fixed top-level `models:` key and
    concatenates the raw lists, doesn't touch individual entries. Real
    validation already happened in cmd_cache_populate before this is
    called; this just gets the (already-known-valid) content into a
    single file the container can mount at one fixed path.

    Caller is responsible for deleting the returned path once done.
    """
    merged = []
    for path in paths:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        merged.extend(data.get("models", []))

    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, prefix="marigold-catalogue-"
    )
    yaml.safe_dump({"models": merged}, tmp)
    tmp.close()
    return tmp.name


def cmd_cache_populate(args):
    from models.catalogue import load_catalogue_from_yaml

    paths = _resolve_models_yaml_paths(args.models_yaml)

    # Fail fast on the host, with a real error, before any container
    # spins up -- rather than a stitched file that only fails once
    # cache-init gets around to it.
    load_catalogue_from_yaml([str(p) for p in paths])

    system_config = _load_toml(_system_config_path())
    env = dict(os.environ)
    env["TAG"] = system_config.get("deployment", {}).get("tag", _package_version())
    env["MARIGOLD_CACHE_DIR"] = str(_cache_dir_from_system_config())
    env["MARIGOLD_PACKAGE_DIR"] = str(paths[0].parent)  # satisfies cache-init's unused /app/marigold mount
    env.setdefault("HF_TOKEN", "")

    stitched_path = _stitch_models_yaml(paths)
    container_path = "/app/marigold-refs/models.yaml"
    env["MARIGOLD_MODEL_CATALOGUE_YAMLS"] = container_path

    command = ["python3", "-m", "tools.model_cli", "download-weights"]
    if args.prune:
        command.append("--prune")

    print(f"marigold: cache dir = {env['MARIGOLD_CACHE_DIR']}", file=sys.stderr)
    print(f"marigold: catalogue = {', '.join(str(p) for p in paths)} (stitched)", file=sys.stderr)
    print(f"marigold: prune = {args.prune}", file=sys.stderr)

    cmd = _compose_base_cmd(["core"]) + [
        "run", "--rm",
        "-v", f"{stitched_path}:{container_path}:ro",
        "cache-init", *command,
    ]
    try:
        result = subprocess.run(cmd, env=env)
    finally:
        os.unlink(stitched_path)
    sys.exit(result.returncode)


def _dir_size_bytes(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def _hf_cache_dirname_to_model_name(dirname: str) -> str:
    """'models--org--name' -> 'org/name', HuggingFace's own cache
    directory convention. Not verified against an actual cache
    directory this session -- worth confirming on first real run."""
    if dirname.startswith("models--"):
        parts = dirname[len("models--"):].split("--", 1)
        if len(parts) == 2:
            return f"{parts[0]}/{parts[1]}"
    return dirname


def cmd_cache_inspect(args):
    cache_dir = _cache_dir_from_system_config()
    models_dir = cache_dir / "data" / "models"

    if not models_dir.exists():
        print(f"cache dir  : {cache_dir}", file=sys.stderr)
        print(f"models dir does not exist: {models_dir}", file=sys.stderr)
        sys.exit(1)

    entries = []
    total_bytes = 0
    for child in sorted(models_dir.iterdir()):
        if not child.is_dir():
            continue
        size = _dir_size_bytes(child)
        total_bytes += size
        entries.append((_hf_cache_dirname_to_model_name(child.name), size))

    print(f"cache location: {models_dir}\n")
    for name, size in entries:
        print(f"  {name:<55} {size / 1e9:>8.2f} GB")
    print(f"\n{len(entries)} model(s), {total_bytes / 1e9:.2f} GB total")


def cmd_cache_stub(args):
    print(f"marigold cache {args.cache_command}: not yet implemented")
    sys.exit(1)


# ---------------------------------------------------------------------------
# package subcommands -- stubs only
# ---------------------------------------------------------------------------

def cmd_package_stub(args):
    print(f"marigold package {args.package_command}: not yet implemented")
    sys.exit(1)


# ---------------------------------------------------------------------------
# argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="marigold")
    parser.add_argument(
        "--version", action="version", version=f"marigold {_package_version()}"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    dep = sub.add_parser("deployment", help="manage a running Marigold deployment")
    dep_sub = dep.add_subparsers(dest="deployment_command", required=True)

    for name, fn, help_text in [
        ("start", cmd_deployment_start, "start the deployment"),
        ("stop", cmd_deployment_stop, "stop the deployment"),
        ("status", cmd_deployment_status, "show container status"),
    ]:
        p = dep_sub.add_parser(name, help=help_text)
        p.add_argument(
            "target", nargs="?", default=".",
            help="deployment directory, or <host>.<package_name> (not yet implemented)",
        )
        p.set_defaults(func=fn)

    logs_p = dep_sub.add_parser("logs", help="tail logs from the deployment")
    logs_p.add_argument(
        "target", nargs="?", default=".",
        help="deployment directory, or <host>.<package_name> (not yet implemented)",
    )
    logs_p.add_argument("service", nargs="?", default=None, help="restrict to one service")
    logs_p.add_argument("--no-follow", action="store_true", help="print current logs and exit, don't tail")
    logs_p.set_defaults(func=cmd_deployment_logs)

    cache = sub.add_parser("cache", help="manage the shared model cache")
    cache_sub = cache.add_subparsers(dest="cache_command", required=True)

    validate_p = cache_sub.add_parser(
        "validate", help="check one or more models.yaml files load cleanly"
    )
    validate_p.add_argument("models_yaml", nargs="+", help="one or more models.yaml files")
    validate_p.set_defaults(func=cmd_cache_validate)

    populate_p = cache_sub.add_parser(
        "populate", help="download missing models, optionally prune unwanted ones"
    )
    populate_p.add_argument(
        "models_yaml", nargs="+",
        help="one or more models.yaml files -- their union is the wanted set",
    )
    populate_p.add_argument(
        "--prune", action="store_true",
        help="remove cached models not present in any given models.yaml",
    )
    populate_p.set_defaults(func=cmd_cache_populate)

    inspect_p = cache_sub.add_parser(
        "inspect", help="list cached models, disk usage, and cache location"
    )
    inspect_p.set_defaults(func=cmd_cache_inspect)

    seed_p = cache_sub.add_parser(
        "seed", help="share cached models with the network via torrent (not yet implemented)"
    )
    seed_p.set_defaults(func=cmd_cache_stub)

    pkg = sub.add_parser("package", help="manage Marigold packages (not yet implemented)")
    pkg_sub = pkg.add_subparsers(dest="package_command", required=True)
    for name in ["repo", "update", "list", "install", "create", "sign", "publish"]:
        p = pkg_sub.add_parser(name)
        p.set_defaults(func=cmd_package_stub)

    return parser


def main():
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(levelname)s:%(name)s:%(message)s",
        stream=sys.stderr,
    )
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
