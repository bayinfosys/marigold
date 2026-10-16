# Marigold -- Applications

An application is a model requirement and the code that uses it. It
declares which models must be in the cache, and carries the code that
runs against them. Installing an application puts it in the cache under
its name; starting it runs its code in its own container against the
platform.

---

## Layout

    my-application/
      marigold.toml     identity, model files, what to run
      models.yaml       the models this application requires
      main.py           the default entrypoint
      ...               any other modules or data

Beyond `marigold.toml`, the layout is the application's own business. A
flat application runs `main.py`; a larger one adds modules and
subdirectories as it needs them. The whole application root is mounted
at `/app`.

---

## marigold.toml

    [application]
    name = "platform-model-test"       # lowercase letters, digits, hyphens
    version = "0.2.0"                  # a label; not compared or ordered
    models_yaml = ["models.yaml"]      # relative to the application root
    compose_files = []                 # services added to the platform, e.g. ["webui"]

    [execution]
    name = "platform-model-test"       # container name; defaults to [application].name
    image = "ghcr.io/bayinfosys/marigold-executor-python"   # optional
    command = ["python", "main.py"]    # optional; defaults to the image's

    [environment]
    SOME_VARIABLE = "value"            # forwarded to the containers

`[application].name` and `version` are required to build or install an
archive: an installed application lives in a content-addressed
directory, so the archive must carry its own identity. Running straight
from a directory, the directory name stands in for a missing name.

`[application].compose_files` adds services to the platform's own list
from the system config. An application that brings open-webui lists
`webui`; starting it adds that service to the shared platform. Whether
the host runs a GPU worker is the host's decision, made in the system
config.

`[execution].image` may carry a tag or a digest, and is then used as
written. An untagged image gets the platform's tag.

Host sections -- `[platform]`, `[cache]`, `[database]` -- are rejected
in an application config. So are `[package]` and `[deployment]`, the
earlier names for `[application]`, each with a message naming the
change.

---

## Lifecycle

    marigold application create ./my-application -o /tmp
    marigold application install /tmp/my-application-0.2.0.tar.gz
    marigold cache populate my-application
    marigold application start my-application
    marigold application logs my-application
    marigold application stop my-application

    marigold application list
    marigold application uninstall my-application
    marigold cache validate my-application

`create` builds a `.tar.gz`, excluding VCS metadata, caches,
virtualenvs and build output, with ownership and permissions stripped
to read and execute.

`install` copies the archive to
`data/applications/_archives/<sha256>.tar.gz`, extracts it to
`data/applications/_src/<digest>/`, and records it in
`data/applications/installed.json` under its name. The same archive
always resolves to the same directory and is extracted once. Installing
a new version under the same name replaces the index entry.

`uninstall` removes the index entry and the extracted tree. The archive
stays, so a reinstall is free; the cache and the catalogue are
untouched.

`cache populate` requires an installed application: the cache container
reads it from the cache, where the CLI put it.

`application start` accepts an installed name, an application
directory, or an archive. The installed index is checked first. A
directory is mounted where it lies, which makes editing an application
in place the development loop; the cache container still needs it
installed to populate its models.

---

## The application contract

What an application can rely on inside its container.

**Mounts**

| Path | Contents | Mode |
|---|---|---|
| `/app` | the application root; the working directory | read-only |
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
Docker socket, the platform database.

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

- Model placeholders: `$name` in model fields, with defaults in
  `models.yaml` and overrides at start.
- Runs: a runs API, run records, and a handler interface for
  applications that serve many requests.
- `api.py`, served by the instance and reached through the platform API.
- Interpreted applications: Prompt and PromptLoop kinds defined by role
  files.
- An application database, requested like `webui`.
- Instance expansion: several containers from one application,
  parameterised by a list or a seed (`MARIGOLD_INSTANCE_SEED`), up to
  `max_count`.
- `--attach`, so `application start` returns the application's exit code.
- Fetching and publishing through remotes, for namespaced names
  (`bayinfosys.simple-rag`).
- Limits on archive size and member count at extraction.
