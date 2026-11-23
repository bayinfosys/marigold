"""The registries a host installs from: the list, and fetching from it.

cli/registry.py builds a registry. This module is the other side: the
[[registry]] entries in marigold-host.toml, and resolving an
application name against them.

    marigold registry add [NAME] URL     append a [[registry]] entry
    marigold registry list               the entries, in search order
    marigold registry remove NAME|URL    remove one

    marigold application install chat          highest version, first registry listing it
    marigold application install chat@v0.0.2   that version

Resolution follows the protocol: GET <url>/marigold-applications.json,
the first registry in file order that lists the name supplies it, and
the archive must match the index's sha256 before it is unpacked and its
files the index's digest after. Registry names are local labels, shown
by list; nothing resolves by them yet.

The host config is edited with tomlkit, so comments and layout survive.
"""

import hashlib
import tempfile

from pathlib import Path
from urllib.parse import urljoin

import httpx
import tomlkit

from packaging.version import InvalidVersion, Version

from cli.host_config import DEFAULT_HOST_CONFIG_PATH, RegistryEntry, host_config_path, parse_host_config
from cli.registry import INDEX_NAME, PROTOCOL

TIMEOUT = 30.0


# ---------------------------------------------------------------------------
# the [[registry]] list
# ---------------------------------------------------------------------------

def _config_file() -> Path:
    """The host config to edit: the one in use, or the default path."""
    return host_config_path() or DEFAULT_HOST_CONFIG_PATH


def _load_document(path: Path) -> tomlkit.TOMLDocument:
    return tomlkit.parse(path.read_text(encoding="utf-8")) if path.exists() else tomlkit.document()


def _save_document(path: Path, document: tomlkit.TOMLDocument) -> None:
    """Validate against HostConfig, then write."""
    text = tomlkit.dumps(document)
    parse_host_config(text, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def add(url: str, name: str | None = None) -> tuple[Path, RegistryEntry]:
    """Append a registry; it is searched after those already listed."""
    entry = RegistryEntry(url=url, name=name)
    path = _config_file()
    document = _load_document(path)

    if "registry" not in document:
        document["registry"] = tomlkit.aot()

    table = tomlkit.table()
    table["url"] = entry.url
    if entry.name:
        table["name"] = entry.name

    document["registry"].append(table)
    _save_document(path, document)

    return path, entry


def remove(key: str) -> tuple[Path, dict]:
    """Remove the registry whose name or url is key."""
    path = _config_file()
    document = _load_document(path)
    entries = document.get("registry", [])
    url = key if key.endswith("/") else key + "/"

    for position, entry in enumerate(entries):
        if entry.get("name") == key or entry.get("url") in (key, url):
            removed = dict(entries[position])
            del entries[position]
            if not entries:
                del document["registry"]
            _save_document(path, document)
            return path, removed

    raise LookupError(f"no registry named or at '{key}' in {path}")


# ---------------------------------------------------------------------------
# resolving and fetching
# ---------------------------------------------------------------------------

def fetch_index(url: str) -> dict:
    """A registry's index."""
    response = httpx.get(urljoin(url, INDEX_NAME), timeout=TIMEOUT, follow_redirects=True)
    response.raise_for_status()
    index = response.json()

    if index.get("protocol") != PROTOCOL:
        raise ValueError(f"{url}: index protocol {index.get('protocol')!r}, this marigold reads {PROTOCOL}")

    return index


def _highest(versions: list[str]) -> str:
    def key(version: str):
        try:
            return (1, Version(version))
        except InvalidVersion:
            return (0, Version("0"))

    return max(versions, key=key)


def resolve(target: str, registries: list[RegistryEntry]) -> tuple[str, str, dict]:
    """(registry url, version, index entry) for 'name' or 'name@version'.

    The first registry, in file order, whose index lists the name
    supplies it.
    """
    name, _, version = target.partition("@")

    if not registries:
        raise LookupError(f"no registries configured; marigold registry add <url>")

    for registry in registries:
        versions = fetch_index(registry.url).get("applications", {}).get(name, {}).get("versions", {})

        if not versions:
            continue

        if version:
            if version not in versions:
                raise LookupError(
                    f"{registry.url} lists {name}, but not version {version} "
                    f"(it has {', '.join(sorted(versions))})"
                )
            return registry.url, version, versions[version]

        chosen = _highest(list(versions))
        return registry.url, chosen, versions[chosen]

    searched = ", ".join(registry.url for registry in registries)
    raise LookupError(f"no registry lists '{name}' (searched {searched})")


def download(registry_url: str, entry: dict, directory: Path) -> Path:
    """Fetch an entry's archive into directory and check its sha256."""
    url = urljoin(registry_url, entry["archive"])
    archive = directory / Path(entry["archive"]).name
    digest = hashlib.sha256()

    with httpx.stream("GET", url, timeout=TIMEOUT, follow_redirects=True) as response:
        response.raise_for_status()
        with open(archive, "wb") as f:
            for chunk in response.iter_bytes():
                f.write(chunk)
                digest.update(chunk)

    if digest.hexdigest() != entry["sha256"]:
        archive.unlink()
        raise ValueError(f"{url}: sha256 {digest.hexdigest()[:12]} does not match the index's {entry['sha256'][:12]}")

    return archive


def fetch(target: str, registries: list[RegistryEntry], directory: Path) -> tuple[Path, str, str, dict]:
    """(archive, registry url, version, index entry) for a name."""
    url, version, entry = resolve(target, registries)
    return download(url, entry, directory), url, version, entry


def temporary_directory() -> tempfile.TemporaryDirectory:
    return tempfile.TemporaryDirectory(prefix="marigold-")
