"""Cache builder -- shared logic.

Contains all cache management logic that does not depend on AWS or local
filesystem configuration. Imported by cache_builder_aws.py and
cache_builder_local.py.
"""

import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import models
from shared.registry import _SPECS

log = logging.getLogger("cache-manager")


# ---------------------------------------------------------------------------
# Cache directory helpers
# ---------------------------------------------------------------------------


def model_to_cache_name(model_name: str) -> str:
    """HuggingFace convention: models--{org}--{repo}"""
    return "models--" + model_name.replace("/", "--")


def dir_size_gb(path: Path) -> float:
    """Recursively sum file sizes under path, return GB.
    NB: count inodes to avoid link double counting
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
    return total / (1024 ** 3)


def cached_model_names(cache_path: Path) -> dict:
    """Scan the cache directory.

    Returns a mapping of model_name -> Path for all models on disk.
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
    """A cached model is considered complete if its snapshots directory
    contains at least one entry.
    """
    snapshots = cache_path / model_to_cache_name(model_name) / "snapshots"
    if not snapshots.exists():
        return False
    return any(snapshots.iterdir())


# ---------------------------------------------------------------------------
# Model caching
# ---------------------------------------------------------------------------


def cache_model(model: dict, cache_dir: str, hf_token: str) -> bool:
    """Call the registered loader for a single model in-process.

    Returns True on success.
    """
    model_type = model.get("type")
    model_name = model.get("name")

    if model.get("auth_required") and not hf_token:
        log.warning("%s requires an HF token but none is set -- skipping", model_name)
        return False

    if model_type not in _SPECS:
        log.error("%s: unknown model type '%s'", model_name, model_type)
        return False

    if hf_token:
        os.environ["HF_TOKEN"] = hf_token

    os.environ["HF_HUB_CACHE"] = cache_dir
    os.environ["HF_HUB_OFFLINE"] = "0"
    os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "0"

    try:
        _SPECS[model_type].loader(
            model_name,
            cache_dir=cache_dir,
            local_files_only=False,
            low_cpu_mem_usage=False,
        )
        return True
    except Exception as e:
        log.error("%s: loader failed [%s]", model_name, str(e))
        return False


# ---------------------------------------------------------------------------
# Build and inspect
# ---------------------------------------------------------------------------


@dataclass
class BuildResult:
    cached:  list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    pruned:  list = field(default_factory=list)
    errors:  list = field(default_factory=list)


def run_build(models_list: list, cache_path: Path, hf_token: str, prune: bool = True) -> BuildResult:
    """Cache all declared models and prune any that are no longer declared.

    Always prunes -- the declared list is the source of truth.
    """
    models.load_all()

    result = BuildResult()
    existing = cached_model_names(cache_path)
    declared = {m["name"] for m in models_list}

    cache_path.mkdir(parents=True, exist_ok=True)

    for model in models_list:
        name = model["name"]

        if name in existing and is_model_complete(cache_path, name):
            log.info("skip %s (complete)", name)
            result.skipped.append(name)
            continue

        if name in existing:
            log.warning("%s: directory exists but appears incomplete, re-caching", name)

        log.info("caching %s", name)
        ok = cache_model(model, str(cache_path), hf_token)
        if ok:
            log.info("cached %s", name)
            result.cached.append(name)
        else:
            log.error("failed to cache %s", name)
            result.errors.append(name)

    if prune:
        for name, path in existing.items():
            if name not in declared:
                log.info("pruning %s", name)
                try:
                    shutil.rmtree(path)
                    log.info("pruned %s", name)
                    result.pruned.append(name)
                except OSError as e:
                    log.error("failed to prune %s: %s", name, e)
                    result.errors.append("prune:%s" % name)

    return result


def run_inspect(models_list: list, cache_path: Path):
    """Report cache contents and drift from the declared model list.

    Returns a list of anomaly names; empty means clean.
    """
    declared = {m["name"] for m in models_list}
    existing = cached_model_names(cache_path)
    anomalies = []

    print("\n--- cache inspection ---")
    print("  declared in config: %i" % len(declared))
    print("  found on disk:      %i\n" % len(existing))

    total_gb = 0.0

    for model in models_list:
        name = model["name"]
        path = cache_path / model_to_cache_name(name)
        complete = is_model_complete(cache_path, name)

        if name not in existing:
            status, gb = "MISSING", 0.0
            anomalies.append(name)
        elif not complete:
            status, gb = "INCOMPLETE", dir_size_gb(path)
            anomalies.append(name)
        else:
            status, gb = "ok", dir_size_gb(path)

        total_gb += gb
        print("  %-12s %-55s %.2f GB" % (status, name, gb))

    undeclared = [n for n in existing if n not in declared]
    if undeclared:
        print()
        for name in undeclared:
            gb = dir_size_gb(existing[name])
            total_gb += gb
            print("  %-12s %-55s %.2f GB" % ("UNDECLARED", name, gb))
            anomalies.append(name)

    print("\n  total cache size: %.2f GB" % total_gb)
    if anomalies:
        print("  anomalies: %i" % len(anomalies))
    print()

    return anomalies


def print_build_summary(result: BuildResult, cache_path: Path):
    total_gb = sum(
        dir_size_gb(cache_path / model_to_cache_name(n))
        for n in list({*result.cached, *result.skipped})
        if (cache_path / model_to_cache_name(n)).exists()
    )

    print("\n--- build summary ---")
    for name in result.cached:
        gb = dir_size_gb(cache_path / model_to_cache_name(name))
        print("  cached:  %s (%.2f GB)" % (name, gb))
    for name in result.skipped:
        print("  skipped: %s (complete)" % name)
    for name in result.pruned:
        print("  pruned:  %s" % name)
    for name in result.errors:
        print("  error:   %s" % name)
    print("\n  total cache size: %.2f GB" % total_gb)
    if result.errors:
        print("  errors: %i" % len(result.errors))
    print()
