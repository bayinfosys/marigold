"""
model_cache_shared.py -- Cache builder shared logic.

Contains all cache management logic that does not depend on AWS or local
filesystem configuration. Imported by the CLI and any cache builder scripts.

Public interface
----------------
run_build(models_list, cache_path, hf_token, prune)
    Download and cache all declared models. Prune undeclared entries if prune=True.
    Returns a BuildResult.

inspect_to_dict(models_list, cache_path)
    Collect cache state as a serialisable dict. Used by the CLI --json path
    and by run_inspect.

run_inspect(models_list, cache_path)
    Print a human-readable cache inspection report to stdout.
    Returns a list of anomaly names; empty means clean.

print_build_summary(result, cache_path)
    Print a human-readable build summary to stdout.
"""

import logging
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import models
from shared.registry import _SPECS

log = logging.getLogger("cache-manager")


# ---------------------------------------------------------------------------
# Cache directory helpers
# ---------------------------------------------------------------------------


def model_to_cache_name(model_name: str) -> str:
    """HuggingFace cache directory convention: models--{org}--{repo}"""
    return "models--" + model_name.replace("/", "--")


def dir_size_gb(path: Path) -> float:
    """Recursively sum file sizes under path, returning GB.

    Counts inodes to avoid double-counting hard links.
    """
    seen = set()
    total = 0
    for f in path.rglob("*"):
        if not f.is_file():
            continue
        inode = f.stat().st_ino
        if inode in seen:
            continue
        seen.add(inode)
        total += f.stat().st_size
    return total / (1024**3)


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
        remainder = entry.name[len("models--") :]
        parts = remainder.split("--")
        if len(parts) >= 2:
            result["/".join(parts)] = entry

    return result


def is_model_complete(cache_path: Path, model_name: str) -> bool:
    """A cached model is considered complete if its snapshots directory
    contains at least one entry.
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

    Each provider implements build, inspect, and prune for its own storage
    and loading strategy. Providers are registered in _PROVIDERS and looked
    up by the provider field in models.yaml.
    """

    def build(self, model: dict, cache_path: Path, hf_token: str) -> bool:
        """Prepare this model for execution. Return True on success."""
        raise NotImplementedError

    def inspect(self, model: dict, cache_path: Path) -> tuple:
        """Return (status, size_gb) for this model.

        Status values: ok | MISSING | INCOMPLETE
        """
        raise NotImplementedError

    def prune(self, name: str, path: Path) -> bool:
        """Remove a stale or undeclared entry. Return True on success."""
        raise NotImplementedError


class HuggingFaceProvider(Provider):

    def build(self, model: dict, cache_path: Path, hf_token: str) -> bool:
        name = model["name"]
        model_type = model.get("type")

        if model.get("auth_required") and not hf_token:
            log.warning("%s requires an HF token but none is set -- skipping", name)
            return False

        if model_type not in _SPECS:
            log.error("%s: unknown model type '%s'", name, model_type)
            return False

        if is_model_complete(cache_path, name):
            log.info("skip %s (complete)", name)
            return True

        if hf_token:
            os.environ["HF_TOKEN"] = hf_token

        os.environ["HF_HUB_CACHE"] = str(cache_path)
        os.environ["HF_HUB_OFFLINE"] = "0"
        os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "0"

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

    def inspect(self, model: dict, cache_path: Path) -> tuple:
        name = model["name"]
        existing = cached_model_names(cache_path)
        path = cache_path / model_to_cache_name(name)

        if name not in existing:
            return ("MISSING", 0.0)
        elif not is_model_complete(cache_path, name):
            return ("INCOMPLETE", dir_size_gb(path))
        else:
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
    """Provider for built-in compute steps that require no downloaded weights."""

    def build(self, model: dict, cache_path: Path, hf_token: str) -> bool:
        return True

    def inspect(self, model: dict, cache_path: Path) -> tuple:
        return ("ok", 0.0)

    def prune(self, name: str, path: Path) -> bool:
        return True


_PROVIDERS = {
    "huggingface": HuggingFaceProvider(),
    "tools": ToolsProvider(),
}


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


@dataclass
class BuildResult:
    cached: list = field(default_factory=list)
    pruned: list = field(default_factory=list)
    errors: list = field(default_factory=list)


def _get_provider(model: dict) -> tuple:
    """Return (provider_key, provider) for a model dict.

    provider is None if the key is not registered.
    """
    provider_key = model.get("provider", "huggingface")
    return provider_key, _PROVIDERS.get(provider_key)


def run_build(
    models_list: list,
    cache_path: Path,
    hf_token: str,
    prune: bool = True,
) -> BuildResult:
    """Download and cache all declared models.

    Prune any entries found on disk that are not in models_list if prune=True.
    The declared list is the source of truth for pruning. Providers that write
    nothing to disk have no-op prune implementations.
    """
    models.load_all()

    result = BuildResult()
    existing = cached_model_names(cache_path)
    declared = {m["name"] for m in models_list}

    cache_path.mkdir(parents=True, exist_ok=True)

    for model in models_list:
        name = model["name"]
        provider_key, provider = _get_provider(model)

        if provider is None:
            log.error("skip %s: unknown provider '%s'", name, provider_key)
            result.errors.append(name)
            continue

        ok = provider.build(model, cache_path, hf_token)
        if ok:
            result.cached.append(name)
        else:
            result.errors.append(name)

    if prune:
        for name, path in existing.items():
            if name not in declared:
                log.info("pruning %s", name)
                provider_key, provider = _get_provider({"name": name})
                if provider.prune(name, path):
                    result.pruned.append(name)
                else:
                    result.errors.append("prune:%s" % name)

    return result


# ---------------------------------------------------------------------------
# Inspect
# ---------------------------------------------------------------------------


def inspect_to_dict(models_list: list, cache_path: Path) -> dict:
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
    declared = {m["name"] for m in models_list}
    existing = cached_model_names(cache_path)
    model_states = {}
    anomalies = []
    total_gb = 0.0

    for model in models_list:
        name = model["name"]
        provider_key, provider = _get_provider(model)

        if provider is None:
            model_states[name] = {"status": "ERROR", "size_gb": 0.0}
            anomalies.append(name)
            continue

        status, gb = provider.inspect(model, cache_path)
        model_states[name] = {"status": status, "size_gb": round(gb, 3)}
        total_gb += gb

        if status in ("MISSING", "INCOMPLETE"):
            anomalies.append(name)

    for name, path in existing.items():
        if name not in declared:
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
