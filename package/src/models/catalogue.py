"""yaml parsing and database access for the model catalogue.

The functions operate on the ModelCatalogueItem objects
"""
import json
import yaml
import logging

from dynawrap.backends.base import DBBackend

from shared.db_models import ModelCatalogueItem
from shared.enums import ModelType


logger = logging.getLogger(__name__)


# Default input/output for each ModelType, applied when a models.yaml
# entry doesn't specify them explicitly. An explicit input:/output: in
# the yaml always wins -- this only fills gaps.
#
# INSTRUCT's "chat"/"chat" matches the existing convention in
# examples/benchmark-llm/models.yaml. TEXT_EMBEDDING/IMAGE_EMBEDDING
# follow shared.enums.ModelModalities' vocabulary (text/image/embedding).
# TTS, TXT2AUDIO, DEPTH, IMG2TXT, TXT2IMG below are reasonable guesses,
# not drawn from an existing yaml entry -- worth confirming against
# actual usage before relying on them.
_DEFAULT_IO_BY_TYPE: dict[ModelType, tuple[str, str]] = {
    ModelType.INSTRUCT:        ("chat",  "chat"),
    ModelType.TEXT_EMBEDDING:  ("text",  "embedding"),
    ModelType.IMAGE_EMBEDDING: ("image", "embedding"),
    ModelType.TTS:             ("text",  "audio"),
    ModelType.TXT2AUDIO:       ("text",  "audio"),
    ModelType.DEPTH:           ("image", "image"),
    ModelType.IMG2TXT:         ("image", "text"),
    ModelType.TXT2IMG:         ("text",  "image"),
}


def load_catalogue_from_yaml(paths: list[str]) -> list[ModelCatalogueItem]:
    """Read one or more models-*.yaml files into a flat catalogue list.

    Anchors and merge keys (<<: *template) are resolved by yaml.safe_load
    itself -- no special handling needed for the _templates: block used
    in the existing models-3060.yaml.

    input/output are filled from _DEFAULT_IO_BY_TYPE when the yaml entry
    doesn't specify them, keyed on the entry's type. An explicit
    input:/output: in the yaml is never overridden.

    Raises ValueError if two files declare the same (model_name, model_type).
    """
    seen: dict[tuple[str, str], str] = {}
    items: list[ModelCatalogueItem] = []

    for path in paths:
        with open(path) as f:
            doc = yaml.safe_load(f)

        logger.info("read %i models in %s", len(doc.get("models", [])), path)

        for raw in doc.get("models", []):

            if "input" not in raw or "output" not in raw:
                defaults = _DEFAULT_IO_BY_TYPE.get(ModelType(raw.get("type")))
                if defaults is not None:
                    raw.setdefault("input", defaults[0])
                    raw.setdefault("output", defaults[1])

            try:
                item = ModelCatalogueItem(source_file=str(path), **raw)
            except Exception as e:
                logger.error("unable to load model from configuration [%s] %s", str(e), json.dumps(raw))
                continue

            if item.hash in seen:
                logger.warning("duplicate model found: %s/%s in %s", item.type.value, item.name, path)

            seen[item.hash] = str(path)
            items.append(item)

    return items


def reconcile_catalogue(backend: DBBackend, table: str, declared: list[ModelCatalogueItem]) -> tuple[list[ModelCatalogueItem], list[ModelCatalogueItem]]:
    """Sync the catalogue table to declared (the current yaml).

    Three cases, by (name, type) identity via .hash:
        in declared only  -> added
        in table only     -> pruned (active=False)
        in both           -> untouched, entirely -- not re-saved at all.
                              This is what lets a worker's active=False
                              from a load failure survive indefinitely
                              across restarts and config syncs.
                              Re-enabling a previously-broken model is
                              a deliberate action (fix it, then flip
                              active back explicitly), never automatic.

    Returns (added, pruned) for logging.
    """
    existing = {item.hash: item for item in get_all_models(backend, table)}
    declared_by_hash = {item.hash: item for item in declared}

    to_add = [item for h, item in declared_by_hash.items() if h not in existing]
    to_prune = [item for h, item in existing.items() if h not in declared_by_hash and item.active]

    for item in to_add:
        backend.save(table, item)
        logger.info("added catalogue entry: %s/%s", item.type.value, item.name)

    for item in to_prune:
        backend.save(table, item.model_copy(update={"active": False}))
        logger.warning("pruned catalogue entry: %s/%s", item.type.value, item.name)

    return to_add, to_prune


def get_models_by_type(
    backend: DBBackend, table: str, model_type: ModelType, active_only: bool = True
) -> list[ModelCatalogueItem]:
    """Fetch every catalogue entry of a given type."""
    items = list(backend.query(table, ModelCatalogueItem, type=str(model_type)))

    logger.info("found %i items for %s", len(items), str(model_type))

    if active_only:
        items = [i for i in items if i.active]

    return items


def get_all_models(backend: DBBackend, table: str):
    """load all models from the database"""
    from shared.enums import ModelType

    models = []

    for mt in ModelType:
        models.extend(get_models_by_type(backend, table, mt))

    return [m for m in models if m]


def get_model(
    backend: DBBackend, table: str, model_type: ModelType, model_name: str
) -> ModelCatalogueItem | None:
    """Fetch a single catalogue entry by its full key."""
    return backend.get(table, ModelCatalogueItem, type=str(model_type), name=model_name)


def save_models(backend: DBBackend, table: str, items: list[ModelCatalogueItem]) -> None:
    """Save a list of catalogue entries. No reconcile/retire logic --
    callers wanting the retire-absent-models behaviour do that themselves."""
    logger.info("saving %i items to '%s'", len(items), table)

    for item in items:
        backend.save(table, item)
