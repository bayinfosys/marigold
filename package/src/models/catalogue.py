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


def load_catalogue_from_yaml(paths: list[str]) -> list[ModelCatalogueItem]:
    """Read one or more models-*.yaml files into a flat catalogue list.

    Anchors and merge keys (<<: *template) are resolved by yaml.safe_load
    itself -- no special handling needed for the _templates: block used
    in the existing models-3060.yaml.

    Raises ValueError if two files declare the same (model_name, model_type).
    """
    seen: dict[tuple[str, str], str] = {}
    items: list[ModelCatalogueItem] = []

    for path in paths:
        with open(path) as f:
            doc = yaml.safe_load(f)

        logger.info("read %i models in %s", len(doc.get("models", [])), path)

        for raw in doc.get("models", []):

            try:
                item = ModelCatalogueItem(source_file=str(path), **raw)
            except Exception as e:
                logger.error("unable to load model from configuration [%s] %s", str(e), json.dumps(raw))

            if item.hash in seen:
                logger.warning("duplicate model found: %s/%s in %s", item.type.value, item.name, path)

            seen[item.hash] = str(path)
            items.append(item)

    return items


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
