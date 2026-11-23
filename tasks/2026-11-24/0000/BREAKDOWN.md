# Breakdown

1. Move api, backend, cli, compose, models, shared and tools from
   package/src/ to package/src/marigold/. Add
   package/src/marigold/__init__.py with a docstring and
   package/src/marigold/cli/__init__.py, which cli lacks. Remove
   package/src/__init__.py.
2. Change every import of api, backend, cli, compose, models, shared
   and tools to `marigold.<name>`, including imports inside functions
   and the handler imports in models/__init__.py. Relative imports stay.
3. pyproject.toml: find the packages under package/src that start with
   `marigold`, key package-data by marigold.compose and marigold.cli,
   and point the entry point at `marigold.cli.main:main`.
4. Read package data with `files("marigold.cli")` in cli/registry.py
   and `files("marigold.compose")` in cli/compose.py.
5. Container commands and paths:
   - Dockerfile: the environment/ COPY paths, `uvicorn
     marigold.api.main:app`, `from marigold.models.entrypoint_handlers
     import local_handler` in both worker stages, and `python3 -m
     marigold.tools.cache_cli populate` for the cache stage
   - docker-compose.core.yaml: the api and cache-init commands
   - cli/commands.py: the cache-init command
   - Makefile: DOCKERFILE and PYTHON_EXECUTOR_DOCKERFILE
6. scripts/config_doc.py: import HostConfig from
   marigold.cli.host_config.
7. Check: every module compiles; every `marigold.` import names a
   module in the tree; `config_doc.py --check` passes; a wheel built
   from the tree holds `marigold` as its only top-level package; in a
   fresh virtual environment, the wheel installs and `marigold --help`
   runs.
