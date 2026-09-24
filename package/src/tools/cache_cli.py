"""
cache_cli.py -- the cache container's entrypoint.

Runs inside the cache image, on the core network, with the model cache
mounted read-write and the cache's applications directory mounted
read-only. It is the only component that writes the model catalogue,
and the only one that creates the platform's tables.

Commands:
    populate        Create the platform tables; cache and register a package.
    inspect-cache   Report cache state against a package's models.yaml.
    validate        Validate a package's models.yaml against the schema.

Packages, not paths:
    Every command takes --package, a directory holding marigold.toml and
    the models.yaml files it names. The marigold CLI installs packages
    into the cache and passes the path of one; nothing here globs a
    catalogue out of the environment, and nothing here reads the host's
    configuration.

Environment (set by docker-compose.core.yaml):
    CACHE_DIR                       model cache root (default: /models)
    MARIGOLD_DATABASE_URL           platform database DSN (populate)
    MARIGOLD_MODEL_CATALOGUE_TABLE  catalogue table name
    HF_TOKEN                        HuggingFace token for gated models
    LOG_LEVEL                       logging verbosity (default: INFO)

Examples:
    python3 -m tools.cache_cli populate
    python3 -m tools.cache_cli populate --package /applications/_src/abc123
    python3 -m tools.cache_cli inspect-cache --package /applications/_src/abc123 --json
"""

import argparse
import json
import logging
import os
import shutil
import sys
import tomllib

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from pydantic import ValidationError

from models.catalogue import load_catalogue_from_yaml
from shared.db_models import ModelCatalogueItem
from shared.model_cache import model_cache_bytes


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("cache-cli")

# suppress noisy HTTP request logging from huggingface_hub and its dependencies
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("huggingface_hub").setLevel(logging.WARNING)
logging.getLogger("huggingface_hub.utils").setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class CliError(Exception):
    """Raised at the point of failure inside any command function.

    Caught once in main(), which logs the message and exits non-zero.
    """

    pass


CommandResult = tuple[dict, bool]


# ---------------------------------------------------------------------------
# Platform tables
# ---------------------------------------------------------------------------

# Created here and nowhere else: this container runs before anything is
# served, on every platform start, so it is the one place table
# creation can live without a startup race between the API and the
# worker.
PLATFORM_TABLES = {
    "MARIGOLD_MODEL_CATALOGUE_TABLE": "model_catalogue",
    "MARIGOLD_RESULTS_TABLE": "results",
    "MARIGOLD_USAGE_TABLE": "usage",
    "MARIGOLD_WORKERS_TABLE": "workers",
}


def _table_name(env_var: str) -> str:
    return os.getenv(env_var, PLATFORM_TABLES[env_var])


# ---------------------------------------------------------------------------
# Packages
# ---------------------------------------------------------------------------


def _package_models(package_path: Path) -> list[ModelCatalogueItem]:
    """The catalogue a package declares, read from the package itself.

    The package is mounted read-only from the cache, so this container
    reads marigold.toml and the models.yaml files it names. [package]
    is the current section; [deployment] is the pre-0.7 name.
    """
    config_path = package_path / "marigold.toml"

    if not config_path.exists():
        raise CliError("no marigold.toml in %s" % package_path)

    with open(config_path, "rb") as f:
        try:
            config = tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            raise CliError("cannot parse %s: %s" % (config_path, e)) from e

    names = (
        config.get("package", {}).get("models_yaml")
        or config.get("deployment", {}).get("models_yaml")
        or ["models.yaml"]
    )

    paths = [package_path / name for name in names]
    missing = [p for p in paths if not p.exists()]

    if missing:
        raise CliError(
            "declared models.yaml not found: " + ", ".join(str(p) for p in missing)
        )

    return load_catalogue_from_yaml([str(p) for p in paths])


@dataclass
class ModelCatalogueContext:
    """The models a package declares, and where the cache is.

    Without a package the catalogue is empty, which is a valid state:
    populate still creates the platform tables, and inspect-cache still
    reports what is on disk.
    """

    models: list[ModelCatalogueItem]
    cache_path: Path

    @classmethod
    def load(cls, package: Optional[str] = None) -> "ModelCatalogueContext":
        cache_path = Path(os.getenv("CACHE_DIR", "/models"))

        if package is None:
            return cls(models=[], cache_path=cache_path)

        return cls(models=_package_models(Path(package)), cache_path=cache_path)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def validate_models(package: Optional[str] = None) -> CommandResult:
    """Validate a package's models.yaml against the live catalogue
    schema (ModelCatalogueItem) and check for duplicate (name, type)
    pairs. Cheap and side-effect-free -- unlike populate, this never
    touches HuggingFace or the database.
    """
    try:
        ctx = ModelCatalogueContext.load(package)
    except ValidationError as e:
        raise CliError("schema validation failed:\n%s" % e)

    seen: dict[tuple[str, str], str] = {}
    duplicates = []

    for m in ctx.models:
        key = (m.name, m.type.value)
        if key in seen:
            duplicates.append({"name": m.name, "type": m.type.value})
        seen[key] = m.source_file

    result = {
        "model_count": len(ctx.models),
        "duplicates": duplicates,
    }
    return result, not duplicates


def download_model(item: ModelCatalogueItem, cache_path: Path, hf_token: str) -> bool:
    """Put one model's weights in the cache. True when they are there.

    A model already complete in the cache is left alone. Provider
    failures are logged and reported as False: one model failing is
    survivable, so the caller decides what that means.
    """
    from tools.model_cache_shared import get_provider

    provider_key, provider = get_provider(item)

    if provider is None:
        log.error("skip %s: unknown provider '%s'", item.name, provider_key)
        return False

    return provider.build(item, cache_path, hf_token)


def _prune_undeclared(items: list[ModelCatalogueItem], cache_path: Path) -> list[str]:
    """Remove cached models this package does not declare.

    Refuses on an empty declared set: pruning against nothing would
    empty a cache whose purpose is outliving any one package.
    """
    from tools.model_cache_shared import cached_model_names

    if not items:
        raise CliError("refusing to prune with no models declared")

    declared = {item.name for item in items}
    pruned = []

    for name, path in cached_model_names(cache_path).items():
        if name in declared:
            continue

        log.info("pruning %s", name)
        shutil.rmtree(path, ignore_errors=True)
        pruned.append(name)

    return pruned


def populate(package: Optional[str] = None, prune: bool = False) -> CommandResult:
    """Create the platform tables, then cache and register a package.

    Each model is registered as its weights are confirmed present, so
    the catalogue fills during a long download and holds only models
    that are in the cache. A model that fails to download gets no row
    and is listed under errors; that is survivable, so this succeeds.

    Without a package this only creates the tables, which is what the
    copy started by `docker compose up` does.
    """
    from dynawrap.backends.postgres import PostgresBackend
    from backend.messaging.postgres import PostgresQueueBackend
    from models import load_all
    from models.catalogue import register_model
    from shared.database import DatabaseUnavailable, get_database_connection

    ctx = ModelCatalogueContext.load(package)
    ctx.cache_path.mkdir(parents=True, exist_ok=True)

    hf_token = os.environ.get("HF_TOKEN", "")

    # Providers dispatch on the registered model types.
    load_all()

    try:
        conn = get_database_connection()
    except DatabaseUnavailable as e:
        raise CliError("catalogue database: %s" % e) from e

    cached, errors = [], []

    try:
        for env_var in PLATFORM_TABLES:
            PostgresBackend.create_table(conn, _table_name(env_var))

        backend = PostgresBackend(conn)
        queues = PostgresQueueBackend(conn)
        table = _table_name("MARIGOLD_MODEL_CATALOGUE_TABLE")

        for item in ctx.models:
            if download_model(item, ctx.cache_path, hf_token):
                register_model(backend, table, queues, item)
                cached.append(item.name)
            else:
                errors.append(item.name)

        pruned = _prune_undeclared(ctx.models, ctx.cache_path) if prune else []
    finally:
        conn.close()

    result = {
        "declared": len(ctx.models),
        "cached": cached,
        "registered": len(cached),
        "pruned": pruned,
        "errors": errors,
        "total_gb": round(
            sum(model_cache_bytes(n, ctx.cache_path) for n in cached) / (1024 ** 3), 3
        ),
    }
    return result, True


def inspect_cache(as_json: bool, package: Optional[str] = None) -> CommandResult:
    """Report cache state against the models a package declares.

    Without a package everything on disk is UNDECLARED, which makes
    this a plain listing of the cache rather than a comparison.
    """
    from tools.model_cache_shared import inspect_to_dict, run_inspect

    ctx = ModelCatalogueContext.load(package)
    state = inspect_to_dict(ctx.models, ctx.cache_path)

    if not as_json:
        run_inspect(state)

    return state, not state["anomalies"]


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cache_cli",
        description="Marigold cache container: tables, weights, catalogue",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="emit structured JSON to stdout",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    pop = sub.add_parser(
        "populate", help="create platform tables, cache and register a package"
    )
    pop.add_argument(
        "--package",
        default=None,
        metavar="DIR",
        help="package directory, as this container sees it",
    )
    pop.add_argument(
        "--prune",
        action="store_true",
        help="remove cached models this package does not declare",
    )

    ic = sub.add_parser("inspect-cache", help="report cache state against a package")
    ic.add_argument("--package", default=None, metavar="DIR", help="package directory")

    val = sub.add_parser("validate", help="validate a package's models.yaml")
    val.add_argument("--package", default=None, metavar="DIR", help="package directory")

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    args = build_parser().parse_args()

    try:
        if args.command == "populate":
            result, success = populate(args.package, prune=args.prune)

        elif args.command == "inspect-cache":
            result, success = inspect_cache(as_json=args.as_json, package=args.package)

        elif args.command == "validate":
            result, success = validate_models(args.package)

        else:
            result, success = {}, False

    except CliError as e:
        log.error("%s", e)
        sys.exit(1)

    # inspect-cache in human mode already printed its table
    if args.command == "inspect-cache" and not args.as_json:
        sys.exit(0 if success else 1)

    if result:
        print(json.dumps(result, indent=2))

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
