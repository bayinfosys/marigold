# Workplan 2026-11-24: one import package

## Goal

`pip install bayis-marigold` puts one import package, `marigold`, and
one command, `marigold`, into an environment. The containers, the CLI
and the documentation name every module by its path under `marigold`.

## Context

The code these tasks touch:

- packaging: pyproject.toml lists seven top-level import packages from
  package/src: api, backend, models, shared, tools, cli and compose
  (compose holds data only); the entry point is `cli.main:main`;
  package-data names the cli and compose packages
- package/src/__init__.py: empty, and makes package/src itself a
  package
- imports: 276 import lines in 82 files name a top-level package,
  including imports inside functions; models/__init__.py imports each
  handler by name in load_all()
- package data: cli/registry.py reads `files("cli")` and cli/compose.py
  reads `files("compose")`
- containers: the Dockerfile copies package/src to /app and imports
  from there without installing the package:
  - api: `uvicorn api.main:app`, in the Dockerfile and in
    docker-compose.core.yaml
  - worker (cpu and gpu): `from models.entrypoint_handlers import
    local_handler`
  - cache: the Dockerfile runs `python3 -m tools.model_cli
    download-weights`, a module that does not exist;
    docker-compose.core.yaml and cli/commands.py run
    `python3 -m tools.cache_cli populate`
- image tags: the CLI sets TAG to its own version unless
  `platform.tag` is set, so a release changes the compose commands and
  the images together
- text: 46 references in docstrings and comments name a module by its
  top-level path, such as `shared.registry`; README.md, model-types.md,
  publishing.md and architecture.md name modules and paths under
  package/src
- installing: README.md and getting-started.md give
  `pip install bayis-marigold`

## Findings

- installing the CLI adds api, backend, models, shared, tools, cli and
  compose to an environment's top-level names, where they shadow, or
  are shadowed by, a user's own modules or another distribution's
  packages with those names (0000)
- the cache image's default command names tools.model_cli, which does
  not exist; compose overrides it, so the image runs only under compose
  (0000)
- the documentation installs the CLI into whatever environment is
  active, alongside the user's own packages (0002)

## Decisions

1. Layout: the seven packages move under `marigold` with their names
   unchanged, `marigold.shared` to `marigold.cli`. A rename of a
   subpackage, such as models to worker, is a later task with its own
   reason.
2. Import name: `marigold`; the distribution name stays
   `bayis-marigold`. The PyPI distribution `marigold`, a small server
   for comparing structured files last released in 2022, may provide
   the same import name; both in one environment would collide.
3. A host config that pins `platform.tag` to a release before this one
   runs the older images under the newer compose commands and fails.
   No compatibility code; the release notes say so.

## Tasks

0000  Move the packages under package/src/marigold/ and import them as
      `marigold.<name>`: every import, pyproject.toml's packages,
      package-data and entry point, the package-data names in the CLI,
      and the commands in the Dockerfile, the compose files and the
      CLI; remove package/src/__init__.py; the cache image's default
      command runs `marigold.tools.cache_cli populate`.

0001  Name each module by its path under `marigold` in docstrings,
      comments, README.md and docs/.
      Depends on 0000.

0002  Give `pipx install bayis-marigold` and `uv tool install
      bayis-marigold` as the ways to install the CLI, in README.md,
      getting-started.md and installing.md, each in an environment of
      its own.
      Depends on 0000.

## Checks

- a wheel built from the branch holds one top-level package,
  `marigold`: `python -m build --wheel` and
  `unzip -l dist/*.whl | awk '{print $4}' | cut -d/ -f1 | sort -u`
- in a fresh virtual environment, `pip install dist/*.whl` then
  `marigold --help`
- `make build`, then the integration cycle: `marigold platform start`,
  `cache populate` and one application, with the worker loading a
  model
