"""
model_cache_shared.py -- cache provider logic.

Providers know how to put one model's weights in the cache, report on
them, and remove them. The loop over a package's models, the database
writes and the reporting live in tools/model_cli.py; this module is
per-model and stateless.

Public interface
----------------
get_provider(item)
    (provider_key, provider) for one catalogue item. provider is None
    when the key is not registered.

cached_model_names(cache_path)
    model_name -> Path for everything on disk.

is_model_complete(cache_path, model_name)
    Whether a cached model looks usable.

inspect_to_dict(catalogue, cache_path)
    Cache state as a serialisable dict, declared against found.

run_inspect(state), print_build_summary_from_dict(result)
    Human-readable reports from those dicts.
"""

import logging
import os
import shutil

from datetime import datetime, timezone
from pathlib import Path

from shared.db_models import ModelCatalogueItem, set_model_config_env
from shared.enums import ModelProvider
from shared.model_cache import cache_dir_bytes
from shared.registry import _SPECS

log = logging.getLogger("marigold.model-cache")


# ---------------------------------------------------------------------------
# Cache directory helpers
# ---------------------------------------------------------------------------


def model_to_cache_name(model_name: str) -> str:
    """HuggingFace cache directory convention: models--{org}--{repo}"""
    return "models--" + model_name.replace("/", "--")


def dir_size_gb(path: Path) -> float:
    """Size under path in GB, counting each physical file once.

    Delegates to shared.model_cache.cache_dir_bytes, which accumulates
    against (st_dev, st_ino): the HuggingFace layout links snapshots to
    blobs, so a plain walk counts each blob once per revision.
    """
    return cache_dir_bytes(path) / (1024 ** 3)


def cached_model_names(cache_path: Path) -> dict:
    """Scan the cache directory.

    Returns a mapping of model_name -> Path for all models found on disk.
    """
    result = {}

    if not cache_path.exists():
        return result

    for entry in cache_path.iterdir():
        if not entry.is_dir():
            continue
        if not entry.name.startswith("models--"):
            continue

        remainder = entry.name[len("models--"):]
        parts = remainder.split("--")

        if len(parts) >= 2:
            result["/".join(parts)] = entry

    return result


def is_model_complete(cache_path: Path, model_name: str) -> bool:
    """A cached model is complete if its snapshots directory has an entry.

    TODO: an interrupted download leaves a snapshot directory holding
    some files, which passes this and then fails at load time. Checking
    for .incomplete blobs would cover the common case.
    """
    snapshots = cache_path / model_to_cache_name(model_name) / "snapshots"

    if not snapshots.exists():
        return False

    return any(snapshots.iterdir())


# ---------------------------------------------------------------------------
# Provider interface
# ---------------------------------------------------------------------------


class Provider:
    """Base class for cache provider implementations.

    Each provider implements build, inspect and prune for its own
    storage and loading strategy. Providers are registered in
    _PROVIDERS and looked up by the provider field in models.yaml.
    """

    def build(self, model: ModelCatalogueItem, cache_path: Path, hf_token: str) -> bool:
        """Prepare this model for execution. Return True on success."""
        raise NotImplementedError

    def inspect(self, model: ModelCatalogueItem, cache_path: Path) -> tuple:
        """Return (status, size_gb) for this model.

        Status values: ok | MISSING | INCOMPLETE
        """
        raise NotImplementedError

    def prune(self, name: str, path: Path) -> bool:
        """Remove a stale or undeclared entry. Return True on success."""
        raise NotImplementedError


class HuggingFaceProvider(Provider):
    """Weights from the HuggingFace hub, cached by its own layout."""

    def build(self, model: ModelCatalogueItem, cache_path: Path, hf_token: str) -> bool:
        name = model.name
        model_type = model.type

        if model_type not in _SPECS:
            log.error("%s: unknown model type '%s'", name, model_type)
            return False

        if is_model_complete(cache_path, name):
            log.info("skip %s (complete)", name)
            return True

        if hf_token:
            os.environ["HF_TOKEN"] = hf_token
        else:
            log.warning("HF_TOKEN not provided")

        # FIXME: these are defined in the container, forcing them here
        # is confusing.
        os.environ["HF_HUB_CACHE"] = str(cache_path)
        os.environ["HF_HUB_OFFLINE"] = "0"
        os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "0"

        # set any env vars given in extra_env
        set_model_config_env(model)

        try:
            _SPECS[model_type].loader(
                name,
                cache_dir=str(cache_path),
                local_files_only=False,
                low_cpu_mem_usage=False,
            )
            return True
        except Exception as e:
            log.error("%s: loader failed [%s]", name, str(e))
            return False

    def inspect(self, model: ModelCatalogueItem, cache_path: Path) -> tuple:
        name = model.name
        path = cache_path / model_to_cache_name(name)

        if name not in cached_model_names(cache_path):
            return ("MISSING", 0.0)

        if not is_model_complete(cache_path, name):
            return ("INCOMPLETE", dir_size_gb(path))

        return ("ok", dir_size_gb(path))

    def prune(self, name: str, path: Path) -> bool:
        try:
            shutil.rmtree(path)
            log.info("pruned %s", name)
            return True
        except OSError as e:
            log.error("failed to prune %s: %s", name, e)
            return False


class ToolsProvider(Provider):
    """Built-in compute steps that require no downloaded weights."""

    def build(self, model: ModelCatalogueItem, cache_path: Path, hf_token: str) -> bool:
        return True

    def inspect(self, model: ModelCatalogueItem, cache_path: Path) -> tuple:
        return ("ok", 0.0)

    def prune(self, name: str, path: Path) -> bool:
        return True


_PROVIDERS = {
    ModelProvider.HUGGINGFACE: HuggingFaceProvider(),
    ModelProvider.TOOLS: ToolsProvider(),
}


def get_provider(model: ModelCatalogueItem) -> tuple:
    """Return (provider_key, provider) for one catalogue item.

    provider is None if the key is not registered.
    """
    return model.provider, _PROVIDERS.get(model.provider)


# ---------------------------------------------------------------------------
# Inspect
# ---------------------------------------------------------------------------


def inspect_to_dict(catalogue: list[ModelCatalogueItem], cache_path: Path) -> dict:
    """Collect cache state as a serialisable dict.

    Shape:
    {
        "inspected_at": "2026-04-25T10:00:00Z",
        "declared":     5,
        "found":        4,
        "total_gb":     12.3,
        "models": {
            "stable-diffusion-v1-5": {"status": "ok",          "size_gb": 4.12},
            "clip-ViT-B-32":         {"status": "MISSING",     "size_gb": 0.0},
            "old-model":             {"status": "UNDECLARED",  "size_gb": 1.5},
        },
        "anomalies": ["clip-ViT-B-32", "old-model"]
    }

    Status values: ok | MISSING | INCOMPLETE | UNDECLARED | ERROR
    """
    declared = {m.name for m in catalogue}
    existing = cached_model_names(cache_path)
    model_states = {}
    anomalies = []
    total_gb = 0.0

    for model in catalogue:
        name = model.name
        provider_key, provider = get_provider(model)

        if provider is None:
            log.error("%s: unknown provider '%s'", name, provider_key)
            model_states[name] = {"status": "ERROR", "size_gb": 0.0}
            anomalies.append(name)
            continue

        status, gb = provider.inspect(model, cache_path)
        model_states[name] = {"status": status, "size_gb": round(gb, 3)}
        total_gb += gb

        if status in ("MISSING", "INCOMPLETE"):
            anomalies.append(name)

    for name, path in existing.items():
        if name in declared:
            continue

        gb = dir_size_gb(path)
        model_states[name] = {"status": "UNDECLARED", "size_gb": round(gb, 3)}
        total_gb += gb
        anomalies.append(name)

    return {
        "inspected_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "declared": len(declared),
        "found": len(existing),
        "total_gb": round(total_gb, 3),
        "models": model_states,
        "anomalies": anomalies,
    }


def run_inspect(state: dict) -> None:
    print("\n--- cache inspection ---")
    print("  declared in config: %i" % state["declared"])
    print("  found on disk:      %i\n" % state["found"])

    for name, entry in state["models"].items():
        print("  %-12s %-55s %.2f GB" % (entry["status"], name, entry["size_gb"]))

    print("\n  total cache size: %.2f GB" % state["total_gb"])

    if state["anomalies"]:
        print("  anomalies: %i" % len(state["anomalies"]))

    print()


def print_build_summary_from_dict(result: dict) -> None:
    print("\n--- build summary ---")

    for name in result.get("cached", []):
        print("  cached:  %s" % name)

    for name in result.get("pruned", []):
        print("  pruned:  %s" % name)

    for name in result.get("errors", []):
        print("  error:   %s" % name)

    print("\n  total cache size: %.2f GB" % result.get("total_gb", 0.0))

    if result.get("errors"):
        print("  errors: %i" % len(result["errors"]))

    print()
