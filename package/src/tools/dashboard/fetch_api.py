"""
Marigold API data fetching.

Reads from the public API using an API key.
Returns raw dicts only -- no transform logic.

The dashboard is designed to run with only an API key and AWS
credentials. No access to internal repo or generated files required.
"""
import logging
from typing import Dict

import requests

from .config import API_BASE, API_HEADERS

log = logging.getLogger(__name__)


def fetch_models_json() -> Dict[str, dict]:
    """
    GET /models.json

    Returns the full model catalogue keyed by model hash.
    Each value contains at minimum: name, type, provider.

    Returns empty dict on any failure -- callers degrade gracefully.
    """
    try:
        r = requests.get(
            "%s/models.json" % API_BASE,
            headers=API_HEADERS,
            timeout=10,
        )
        if r.status_code == 200:
            return r.json()
        log.warning("GET /models.json returned %s", r.status_code)
        return {}
    except requests.exceptions.ConnectionError:
        log.warning("GET /models.json: connection failed -- is MARIGOLD_API_BASE set?")
        return {}
    except Exception as e:
        log.warning("fetch_models_json: %s", e)
        return {}
