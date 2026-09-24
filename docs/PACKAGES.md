# Marigold -- Packages

A package is a model requirement and an application. It declares which
models must be in the cache, and carries the code that runs against
them. Installing a package puts it in the cache under its name; starting
it runs its code in its own container against the platform.

---

## Layout

    my-package/
      marigold.toml     identity, model files, what to run
      models.yaml       the models this package requires
      main.py           the default entrypoint
      ...               any other modules, data or workflows

Beyond `marigold.toml`, the layout is the package's own business. A
flat package runs `main.py`; a larger one adds modules and
subdirectories as it needs them. The whole package root is mounted at
`/app`.

---

## marigold.toml

    [package]
    name = "platform-model-test"       # lowercase letters, digits, hyphens
    version = "0.2.0"                  # a label; not compared or ordered
    models_yaml = ["models.yaml"]      # relative to the package root
    compose_files = []                 # additions to the platform, e.g. ["gpu"] or ["webui"]

    [execution]
    name = "platform-model-test"       # application name; defaults to [package].name
    image = "ghcr.io/bayinfosys/marigold-executor-python"   # optional
    command = ["python", "main.py"]    # optional; defaults to the image's

    [environment]
    SOME_VARIABLE = "value"            # forwarded to the containers

`[package].compose_files` adds files to the platform's own list from the
system config. A package that needs a GPU lists `gpu`; one that brings
open-webui lists `webui`. Starting such a package reconfigures the
shared platform to include them.

`[execution].image` may carry a tag or a digest, and is then used as
written. An untagged image gets the platform's tag.

`[deployment]` is the pre-0.7 name for `models_yaml` and the platform's
compose files, and is still read with a warning.

---

## Lifecycle

    marigold package create ./my-package -o /tmp
    marigold package install /tmp/my-package-0.2.0.tar.gz
    marigold cache populate my-package
    marigold application start my-package
    marigold application logs my-package
    marigold application stop my-package

    marigold package list
    marigold package uninstall my-package
    marigold cache validate my-package

`create` builds a `.tar.gz`, excluding VCS metadata, caches,
virtualenvs and build output, with ownership and permissions stripped
to read and execute.

`install` copies the archive to `data/packages/<sha256>.tar.gz`,
extracts it to `data/applications/_src/<digest>/`, and records it in
`data/packages/installed.json` under its name. The same archive always
resolves to the same directory and is extracted once. Installing a new
version under the same name replaces the index entry.

`cache populate` requires an installed package: the cache container
reads it from the cache, where the CLI put it.

`application start` accepts an installed name, a package directory, or
an archive. The installed index is checked first. A directory is
mounted where it lies, which makes editing a package in place the
development loop; the cache container still needs it installed to
populate its models.

---

## The application contract

What an application can rely on inside its container.

**Mounts**

| Path | Contents | Mode |
|---|---|---|
| `/app` | the package root; the working directory | read-only |
| `/outputs` | this application's own output directory | read-write |

**Environment**

| Variable | Value |
|---|---|
| `MARIGOLD_API_BASE` | the API, `http://api:8000` |
| `MARIGOLD_APPLICATION_NAME` | the application name |
| `MARIGOLD_APPLICATION_ID` | the instance identity; equal to the name for a single instance |
| `LOG_LEVEL` | from the host, default `INFO` |
| anything in `[environment]` | as declared |

**Network**: the `marigold-applications` network. The API is reachable;
Postgres, the worker and the cache container are not.

**Lifecycle**: `restart: "no"`. A script that exits stays exited, with
its exit code visible in `marigold application status`. A long-running
application -- a FastAPI service, an agent loop -- runs until stopped.

**Never available**: the host filesystem beyond the two mounts, the
Docker socket, the database.

---

## Making requests

Every submission route takes a JSON body with `model` and the
capability's fields, and returns a `message_id` with a `Location`
header naming the poll route. Polling returns 202 until the job is
terminal, then 200 with `status` of `complete` or `error`.

Two fields on every request matter to applications:

- `application_id` -- set it from `MARIGOLD_APPLICATION_ID`. It is
  recorded against usage, and it is part of the request hash, so
  identical requests from different applications are distinct jobs.
- `nonce` -- identical bodies return a cached result. A fresh nonce
  forces a new sample, which a smoke test or an agent sampling a
  distribution needs.

`platform-model-test` in marigold-examples is the reference: it lists
the catalogue, submits one request per model, polls, and exits 0 only
if every tested model completed.

---

## Not yet built

- Instance expansion: several containers from one package, parameterised
  by a list or a seed (`MARIGOLD_INSTANCE_SEED`), up to `max_count`.
- A payload file passed to the application at start.
- `--attach`, so `application start` returns the application's exit code.
- Repository resolution for namespaced names (`bayinfosys.simple-rag`),
  signing and publishing.
- Limits on archive size and member count at extraction.
