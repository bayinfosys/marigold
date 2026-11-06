"""Registry build: every application under a root in, a static registry out.

A registry is a directory any static host can serve. The build writes
two layers into it:

    protocol   marigold-applications.json
               applications/<name>-<version>.tar.gz
    catalogue  applications/<name>/index.md and models.md
               _data/marigold.json
               a site template: _config.yml, _layouts/, assets/, the
               front page, llms.txt and sitemap.xml

The protocol is complete without Jekyll, and a loader reads only the
protocol. The catalogue is Jekyll source: `jekyll build` renders it into
_site/, beside copies of the protocol files. Absolute URLs are Jekyll's,
from site.url and site.baseurl, set where the site is rendered.

The site template is the package's own (cli/site) with an optional
template directory laid over it: a file in the template replaces the
default at the same path, and anything else is added. The template
presents; the build supplies the data, in _data/marigold.json and each
page's front matter. Commands shown to readers are part of that data.

Every directory under the root holding marigold.toml is published. The
registry's identity comes from marigold-registry.toml at the root
(cli.registry_config). Everything else is derived from the archives:
the build writes each archive, extracts it to a temporary directory,
and takes the index entry, the README and the declared models from
there. Nothing is maintained by hand, and nothing depends on a previous
build: the same sources and template give the same registry.
"""

import json
import os
import shutil
import tempfile

from importlib.resources import files
from pathlib import Path

from packaging.version import Version

from cli import applications, archives
from cli.application_config import ApplicationConfig
from cli.config import (
    APPLICATION_CONFIG_NAME,
    load_application_config,
    load_application_toml,
    marigold_version,
)

PROTOCOL = 1
INDEX_NAME = "marigold-applications.json"
APPLICATIONS_SUBDIR = "applications"
README_NAME = "README.md"
HUGGINGFACE_URL = "https://huggingface.co/"
PROJECT_URL = "https://marigold.run"
PROJECT_REPOSITORY = "https://github.com/bayinfosys/marigold"
DATA_PATH = "_data/marigold.json"


# Written into every build. A non-empty output directory is cleared only
# when it holds this marker, so a build never empties a directory it did
# not write. Jekyll skips dotfiles, so the marker stays out of _site.
MARKER = ".marigold-registry"

# The default site template, shipped as package data.
DEFAULT_SITE = files("cli").joinpath("site")

# Paths the build writes. A site template containing one is an error:
# it would replace generated content. _pages.yml is written by the
# Pages workflow with the site's URL.
GENERATED_PATHS = (INDEX_NAME, APPLICATIONS_SUBDIR, DATA_PATH, MARKER, "_pages.yml")

# A template providing either replaces the default front page.
FRONT_PAGES = ("index.html", "index.md")

# Commands shown to readers. Templates substitute %registry%, %name%,
# %archive% and %archive_name%. The placeholders avoid braces: Liquid ends
# a {{ }} tag at the first '}', even inside a quoted string.
INSTALL_STEPS = [
    "marigold registry add %registry%",
    "marigold application install %name%",
]

def _source_url(version: str) -> str:
    """The marigold source this registry was built with.

    A release has a tag, v<version>, so it links to the source at that
    tag. A development build has none, so it links to the repository.
    """
    parsed = Version(version)

    if parsed.is_devrelease or parsed.local:
        return PROJECT_REPOSITORY

    return f"{PROJECT_REPOSITORY}/tree/v{parsed}"

# ---------------------------------------------------------------------------
# discovery of applications
# ---------------------------------------------------------------------------

def discover(root: Path, out: Path) -> list[Path]:
    """Every application directory under root, sorted.

    A directory holding marigold.toml is an application, at any depth.
    Hidden directories and the output directory are not searched. A
    marigold.toml inside another application's directory is an error,
    since it would be both an application and part of the other's
    archive. Nothing else is excluded: a directory leaves the registry
    when its marigold.toml does.
    """
    root = root.resolve()
    out = out.resolve()

    if not root.is_dir():
        raise FileNotFoundError(f"not a directory: {root}")

    found = []

    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)

        dirnames[:] = sorted(
            d for d in dirnames
            if not d.startswith(".") and (current / d).resolve() != out
        )

        if APPLICATION_CONFIG_NAME in filenames:
            found.append(current)

    found.sort()

    for outer in found:
        for inner in found:
            if inner != outer and outer in inner.parents:
                raise ValueError(
                    f"{inner} holds {APPLICATION_CONFIG_NAME} inside the "
                    f"application at {outer}; remove one of them"
                )

    return found


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------

def build(
    root: Path,
    out: Path,
    *,
    title: str,
    description: str,
    urls: dict[str, str] | None = None,
    front_page: Path | None = None,
    site: Path | None = None,
) -> tuple[dict, list[str]]:
    """Build the registry under root into out. Returns (index, warnings).

    title, description and urls are the registry's identity, from
    marigold-registry.toml. front_page is Markdown for registry visitors,
    shown on the front page above the usage. site is a template
    directory laid over the default.

    The index is written last, so a failed build leaves no index and the
    directory is not a usable registry.
    """
    out = out.resolve()
    sources = discover(root, out)

    if not sources:
        raise FileNotFoundError(f"no {APPLICATION_CONFIG_NAME} found under {root.resolve()}")

    identities = _identities(sources)

    _prepare_output(out)
    _write_template(out, site)

    index: dict = {"protocol": PROTOCOL, "applications": {}}
    model_counts: dict[str, int] = {}
    links: dict[str, dict[str, str]] = {}
    warnings: list[str] = []

    for name, (version, source) in sorted(identities.items()):
        archive, _ = applications.build_archive(source, out / APPLICATIONS_SUBDIR)
        contents = _read_archive(archive)
        entry = _entry(archive, out=out, config=contents["config"])

        index["applications"][name] = {"versions": {version: entry}}
        model_counts[name] = len(contents["models"])
        links[name] = contents["config"].application.urls

        if contents["readme"] is None:
            warnings.append(f"{name}: no {README_NAME}; its catalogue page shows the description only")
        if not entry["description"]:
            warnings.append(f"{name}: no [application].description")

        _write_application_pages(
            out,
            name=name,
            version=version,
            entry=entry,
            contents=contents,
        )

    front_text = front_page.read_text(encoding="utf-8") if front_page else None

    _check_consistency(out, index)
    _write_data(
        out,
        index=index,
        model_counts=model_counts,
        links=links,
        title=title,
        description=description,
        urls=urls or {},
        front_page=front_text,
    )
    _write_index(out, index)

    return index, warnings


def _identities(sources: list[Path]) -> dict[str, tuple[str, Path]]:
    """name -> (version, source), checked before anything is written.

    Each application must declare name and version. Two directories
    declaring one name is an error, since one would overwrite the
    other's archive.
    """
    found: dict[str, tuple[str, Path]] = {}

    for source in sources:
        config = load_application_toml(source / APPLICATION_CONFIG_NAME)
        name, version = applications.application_identity(
            source, config, require_declared=True
        )

        if name in found:
            raise ValueError(f"'{name}' is declared by both {found[name][1]} and {source}")

        found[name] = (version, source)

    return found


def _prepare_output(out: Path) -> None:
    """An empty output directory, or a previous build's, cleared."""
    if out.exists() and any(out.iterdir()):
        if not (out / MARKER).is_file():
            raise ValueError(
                f"{out} is not empty and was not written by a registry "
                "build; choose an empty directory"
            )

        for child in out.iterdir():
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()

    (out / APPLICATIONS_SUBDIR).mkdir(parents=True)
    (out / MARKER).write_text(
        "Written by marigold registry build. The next build clears this directory.\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# site template
# ---------------------------------------------------------------------------

def _copy_tree(source, target: Path) -> None:
    """Copy a directory tree from a Path or an importlib.resources
    Traversable. Dotfiles and Jekyll output are not copied."""
    target.mkdir(parents=True, exist_ok=True)

    for child in sorted(source.iterdir(), key=lambda c: c.name):
        if child.name.startswith(".") or child.name == "_site":
            continue

        destination = target / child.name

        if child.is_dir():
            _copy_tree(child, destination)
        else:
            destination.write_bytes(child.read_bytes())


def _write_template(out: Path, site: Path | None) -> None:
    """The default site, with the given template laid over it."""
    _copy_tree(DEFAULT_SITE, out)

    if site is None:
        return

    site = site.resolve()

    if not site.is_dir():
        raise FileNotFoundError(f"site template not found: {site}")

    clashes = [path for path in GENERATED_PATHS if (site / path).exists()]

    if clashes:
        raise ValueError(
            f"{site} contains paths the registry build writes: {', '.join(clashes)}"
        )

    if any((site / name).exists() for name in FRONT_PAGES):
        for name in FRONT_PAGES:
            (out / name).unlink(missing_ok=True)

    _copy_tree(site, out)


# ---------------------------------------------------------------------------
# archives and the index
# ---------------------------------------------------------------------------

def _read_archive(archive: Path) -> dict:
    """What the index and the catalogue take from an archive.

    The config, the README, the parsed models and the models.yaml text
    as written. Read from the extracted archive, so every page and every
    entry describes what was published.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = archives.extract_to(archive, Path(tmp))
        config_path = root / APPLICATION_CONFIG_NAME

        config = load_application_config(config_path)
        models = applications.application_models(root, load_application_toml(config_path))
        model_files = {
            name: (root / name).read_text(encoding="utf-8")
            for name in config.application.models_yaml
        }

        readme_path = root / README_NAME
        readme = readme_path.read_text(encoding="utf-8") if readme_path.is_file() else None

    return {"config": config, "models": models, "model_files": model_files, "readme": readme}


def _entry(archive: Path, *, out: Path, config: ApplicationConfig) -> dict:
    """The index entry for one archive."""
    return {
        "archive": archive.relative_to(out).as_posix(),
        "sha256": archives.archive_digest(archive),
        "description": config.application.description or "",
        "requires": config.application.requires,
    }


def _versions(application: dict) -> list[tuple[str, dict]]:
    """An application's versions in PEP 440 order."""
    return sorted(application["versions"].items(), key=lambda item: Version(item[0]))


def _check_consistency(out: Path, index: dict) -> None:
    """Every archive the index names exists and has the recorded digest."""
    for name, application in index["applications"].items():
        for version, entry in application["versions"].items():
            path = out / entry["archive"]

            if not path.is_file():
                raise ValueError(f"{name} {version}: {path} is missing")

            if archives.archive_digest(path) != entry["sha256"]:
                raise ValueError(f"{name} {version}: {path} does not match its digest")


def _write_index(out: Path, index: dict) -> None:
    text = json.dumps(index, indent=2) + "\n"
    (out / INDEX_NAME).write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# catalogue pages and data
# ---------------------------------------------------------------------------

def _front_matter(fields: dict) -> str:
    """YAML front matter. JSON scalars and lists are valid YAML, so
    json.dumps quotes every value safely."""
    lines = ["---"]
    lines += [f"{key}: {json.dumps(value)}" for key, value in fields.items()]
    lines += ["---", ""]
    return "\n".join(lines)


def _raw(text: str) -> str:
    """Content Liquid must leave alone: a README with '{{' in a code
    block would otherwise be evaluated as a template."""
    return "{% raw %}\n" + text + "\n{% endraw %}\n"


def _cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _without_title(readme: str) -> str:
    """The README without a leading level-1 heading.

    The page layout prints the application name as the title, so a
    README opening with '# <name>' would print it twice. Only the first
    non-blank line is considered; the archive's README is unchanged.
    """
    lines = readme.splitlines()

    for i, line in enumerate(lines):
        if not line.strip():
            continue
        if line.startswith("# "):
            return "\n".join(lines[:i] + lines[i + 1:])
        break

    return readme


def _value(field) -> str:
    """An enum's value, or the field as a string."""
    return str(getattr(field, "value", field) or "")


def _models_markdown(models: list, model_files: dict[str, str]) -> str:
    """The models page body: a table of parsed models, then each
    declared models.yaml as written."""
    rows = [
        "| Model | Type | Provider | Input | Output |",
        "|---|---|---|---|---|",
    ]

    for item in models:
        provider = _value(item.provider)
        name = _cell(item.name)

        if provider == "huggingface":
            name = f"[{name}]({HUGGINGFACE_URL}{item.name})"

        rows.append(
            f"| {name} | {_value(item.type)} | {provider} "
            f"| {_value(getattr(item, 'input', ''))} "
            f"| {_value(getattr(item, 'output', ''))} |"
        )

    sections = ["\n".join(rows)]

    for filename, text in model_files.items():
        sections.append(f"## {filename}\n\n```yaml\n{text.rstrip()}\n```")

    return "\n\n".join(sections) + "\n"


def _write_application_pages(
    out: Path,
    *,
    name: str,
    version: str,
    entry: dict,
    contents: dict,
) -> None:
    """applications/<name>/index.md and models.md.

    'name' is a Jekyll built-in page variable (the source filename), so
    the application's name goes under 'application'. 'root' is the path
    from the page back to the registry root, for relative links.
    """
    directory = out / APPLICATIONS_SUBDIR / name
    directory.mkdir()

    archive_name = Path(entry["archive"]).name

    common = {
        "root": "../../",
        "application": name,
        "version": version,
        "description": entry["description"],
        "archive": f"../{archive_name}",
        "archive_name": archive_name,
        "archive_path": entry["archive"],
        "sha256": entry["sha256"],
        "requires": entry["requires"],
        "model_count": len(contents["models"]),
        "urls": contents["config"].application.urls,
    }

    readme = contents["readme"]
    body = _without_title(readme) if readme is not None else entry["description"]

    (directory / "index.md").write_text(
        _front_matter({"layout": "application", "title": name, **common}) + _raw(body),
        encoding="utf-8",
    )

    (directory / "models.md").write_text(
        _front_matter({"layout": "models", "title": f"{name} models", **common})
        + _raw(_models_markdown(contents["models"], contents["model_files"])),
        encoding="utf-8",
    )


def _write_data(
    out: Path,
    *,
    index: dict,
    model_counts: dict[str, int],
    links: dict[str, dict[str, str]],
    title: str,
    description: str,
    urls: dict[str, str],
    front_page: str | None,
) -> None:
    """_data/marigold.json: everything a template reads as site.data.marigold."""
    listing = []

    for name, application in sorted(index["applications"].items()):
        for version, entry in _versions(application):
            listing.append({
                "name": name,
                "version": version,
                "description": entry["description"],
                "page": f"{APPLICATIONS_SUBDIR}/{name}/",
                "archive": entry["archive"],
                "sha256": entry["sha256"],
                "requires": entry["requires"],
                "model_count": model_counts.get(name, 0),
                "urls": links.get(name, {}),
            })

    data = {
        "title": title,
        "description": description,
        "urls": urls,
        "version": marigold_version(),
        "source_url": _source_url(marigold_version()),
        "index": INDEX_NAME,
        "front_page": front_page,
        "install_steps": INSTALL_STEPS,
        "applications": listing,
        "project_url": PROJECT_URL,
    }

    path = out / DATA_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
