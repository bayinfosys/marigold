"""Registry build: application directories in, a static registry out.

A registry is a directory any static host can serve:

    marigold-applications.json            the index
    applications/<name>-<version>.tar.gz  the archives
    applications/<name>/index.md          catalogue: the README
    applications/<name>/models.md         catalogue: the declared models
    index.md, _config.yml, _layouts/      catalogue site, Jekyll source

The index and the archives are the protocol, and the only files a
loader reads. The rest is Jekyll source for an optional catalogue:
`jekyll build` turns the directory into _site/, which holds the same
protocol files beside the HTML. Served without Jekyll, the directory
is still a complete registry.

Everything is derived from the archives: the build writes each
archive, extracts it to a temporary directory, and takes the index
entry, the README and the declared models from there. Nothing is
maintained by hand, and nothing depends on a previous build: the same
sources give the same registry.
"""

import json
import os
import shutil
import tempfile

from pathlib import Path

from cli import applications, archives
from cli.application_config import ApplicationConfig
from cli.config import (
    APPLICATION_CONFIG_NAME,
    load_application_config,
    load_application_toml,
)

PROTOCOL = 1
INDEX_NAME = "marigold-applications.json"
APPLICATIONS_SUBDIR = "applications"
README_NAME = "README.md"
HUGGINGFACE_URL = "https://huggingface.co/"

# What a build writes at the top of its output directory, plus what
# Jekyll writes there. A directory holding anything else is not a
# previous build, and is left alone.
OUTPUT_ENTRIES = (
    INDEX_NAME, APPLICATIONS_SUBDIR, "index.md", "_config.yml", "_layouts",
    "_site", ".jekyll-cache", ".jekyll-metadata",
)


# ---------------------------------------------------------------------------
# discovery
# ---------------------------------------------------------------------------

def discover(paths: list[Path], out: Path) -> list[Path]:
    """Application directories under the given paths, sorted.

    A path holding marigold.toml is an application. Any other directory
    is searched. An application's subdirectories belong to it and are
    not searched, and hidden directories, excluded names and the output
    directory are skipped.
    """
    found = set()
    out = out.resolve()

    for root in paths:
        root = root.resolve()

        if not root.is_dir():
            raise FileNotFoundError(f"not a directory: {root}")

        for dirpath, dirnames, filenames in os.walk(root):
            current = Path(dirpath)

            if APPLICATION_CONFIG_NAME in filenames:
                found.add(current)
                dirnames.clear()
                continue

            dirnames[:] = sorted(
                d for d in dirnames
                if not d.startswith(".")
                and d not in archives.EXCLUDED_NAMES
                and (current / d).resolve() != out
            )

    return sorted(found)


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------

def build(
    paths: list[Path],
    out: Path,
    front_page: Path | None = None,
) -> tuple[dict, list[str]]:
    """Build a registry into out. Returns (index, warnings).

    The index is written last, so a failed build leaves no index and the
    directory is not a usable registry.
    """
    out = out.resolve()
    sources = discover(paths, out)

    if not sources:
        raise FileNotFoundError(
            "no applications found under: " + ", ".join(str(p) for p in paths)
        )

    identities = _identities(sources)
    _prepare_output(out)

    index: dict = {"protocol": PROTOCOL, "applications": {}}
    model_counts: dict[str, int] = {}
    warnings: list[str] = []

    for name, (version, source) in sorted(identities.items()):
        archive, _ = applications.build_archive(source, out / APPLICATIONS_SUBDIR)
        contents = _read_archive(archive)
        entry = _entry(archive, out, contents["config"])

        index["applications"][name] = {"versions": {version: entry}}
        model_counts[name] = len(contents["models"])

        if contents["readme"] is None:
            warnings.append(f"{name}: no {README_NAME}; its catalogue page shows the description only")
        if not entry["description"]:
            warnings.append(f"{name}: no [application].description")

        _write_application_pages(out, name, version, entry, contents)

    _check_consistency(out, index)
    _write_site(out, index, model_counts, front_page)
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
    if out.exists():
        foreign = sorted(p.name for p in out.iterdir() if p.name not in OUTPUT_ENTRIES)

        if foreign:
            raise ValueError(
                f"{out} holds files a registry build did not write "
                f"({', '.join(foreign[:5])}); choose an empty directory"
            )

        for name in OUTPUT_ENTRIES:
            path = out / name
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()

    (out / APPLICATIONS_SUBDIR).mkdir(parents=True)


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


def _entry(archive: Path, out: Path, config: ApplicationConfig) -> dict:
    """The index entry for one archive."""
    return {
        "archive": archive.relative_to(out).as_posix(),
        "sha256": archives.archive_digest(archive),
        "description": config.application.description or "",
        "requires": config.application.requires,
    }


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
# catalogue (Jekyll source)
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
    out: Path, name: str, version: str, entry: dict, contents: dict,
) -> None:
    """applications/<name>/index.md and models.md.

    'name' is a Jekyll built-in page variable (the source filename), so
    the application's name goes under 'application'.
    """
    directory = out / APPLICATIONS_SUBDIR / name
    directory.mkdir()

    archive_name = Path(entry["archive"]).name
    common = {
        "application": name,
        "version": version,
        "description": entry["description"],
        "archive": f"../{archive_name}",
        "archive_name": archive_name,
        "sha256": entry["sha256"],
        "requires": entry["requires"],
        "model_count": len(contents["models"]),
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


def _write_site(
    out: Path, index: dict, model_counts: dict[str, int], front_page: Path | None,
) -> None:
    (out / "_config.yml").write_text(CONFIG_YML, encoding="utf-8")

    layouts = out / "_layouts"
    layouts.mkdir()
    (layouts / "default.html").write_text(DEFAULT_LAYOUT, encoding="utf-8")
    (layouts / "application.html").write_text(APPLICATION_LAYOUT, encoding="utf-8")
    (layouts / "models.html").write_text(MODELS_LAYOUT, encoding="utf-8")

    rows = [
        "| Application | Version | Description | Models |",
        "|---|---|---|---|",
    ]

    for name, application in sorted(index["applications"].items()):
        page = f"{APPLICATIONS_SUBDIR}/{name}/"

        for version, entry in sorted(application["versions"].items()):
            rows.append(
                f"| [{name}]({page}) | {version} | {_cell(entry['description'])} "
                f"| [{model_counts.get(name, 0)}]({page}models.html) |"
            )

    intro = _raw(front_page.read_text(encoding="utf-8")) if front_page else ""
    fields = {"layout": "default", "title": "Marigold applications"}

    (out / "index.md").write_text(
        _front_matter(fields) + intro + "\n" + "\n".join(rows) + "\n",
        encoding="utf-8",
    )


CONFIG_YML = """\
title: Marigold applications
markdown: kramdown
kramdown:
  input: GFM
"""

DEFAULT_LAYOUT = """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ page.title }}</title>
<style>
body { font-family: system-ui, sans-serif; max-width: 52rem; margin: 2rem auto; padding: 0 1rem; line-height: 1.5; }
pre, code { font-family: ui-monospace, monospace; }
pre { overflow-x: auto; padding: 0.75rem; background: #f4f4f4; }
table { border-collapse: collapse; }
th, td { padding: 0.25rem 0.75rem; border-bottom: 1px solid #ddd; text-align: left; vertical-align: top; }
td:first-child, th:first-child { white-space: nowrap; }
.crumbs { font-size: 0.9rem; }
</style>
</head>
<body>
{{ content }}
</body>
</html>
"""

APPLICATION_LAYOUT = """\
---
layout: default
---
<p class="crumbs"><a href="../../index.html">Applications</a> / {{ page.application }}</p>
<h1>{{ page.application }}</h1>
<p>{{ page.description | escape }}</p>
<pre><code>marigold application install {{ page.application }}=={{ page.version }}</code></pre>
<table>
<tr><th>Version</th><td>{{ page.version }}</td></tr>
<tr><th>Models</th><td><a href="models.html">{{ page.model_count }} declared</a></td></tr>
<tr><th>Archive</th><td><a href="{{ page.archive }}">{{ page.archive_name }}</a></td></tr>
<tr><th>sha256</th><td><code>{{ page.sha256 }}</code></td></tr>
{% if page.requires.size > 0 %}<tr><th>Requires</th><td>{{ page.requires | join: ", " | escape }}</td></tr>{% endif %}
</table>
{{ content }}
"""

MODELS_LAYOUT = """\
---
layout: default
---
<p class="crumbs"><a href="../../index.html">Applications</a> / <a href="index.html">{{ page.application }}</a> / models</p>
<h1>{{ page.application }}: models</h1>
<p>Declared by version {{ page.version }}: {{ page.model_count }}.</p>
{{ content }}
"""
