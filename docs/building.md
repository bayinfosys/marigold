---
title: Building an application
description: The files an application holds, how to declare its models, what an instance can rely on, and how to run and package it.
nav_order: 3
---

# Building an application

## Layout

```
my-app/
  marigold.toml     identity, model files, what to run
  models.yaml       the models this application requires
  main.py           the entrypoint
  README.md
```

Beyond `marigold.toml`, the layout is the application's own. A larger
application adds modules, data directories and further `models.yaml`
files as it needs them.

## marigold.toml

```toml
[application]
name = "my-app"
version = "0.1.0"
description = "One sentence saying what the application does."
models_yaml = ["models.yaml"]

[application.urls]
repository = "https://github.com/<owner>/<repo>"

[execution]
command = ["python", "main.py"]

[environment]
EXAMPLE_SETTING = "value"
```

| Key | Required | Meaning |
|---|---|---|
| `[application].name` | to package | lowercase letters and digits, single hyphens between them |
| `[application].version` | to package | a quoted PEP 440 version, such as `"0.1.0"` |
| `[application].description` | no | shown in registry listings and catalogue pages |
| `[application].models_yaml` | no | model files to read, relative to the application root; default `["models.yaml"]` |
| `[application].compose_files` | no | platform services the application adds, such as `["webui"]` |
| `[application].requires` | no | other applications this one uses, as `name>=version`, installed with it |
| `[application.urls]` | no | links shown on the catalogue page, such as `repository` |
| `[execution].command` | no | the command the instance runs, as a list; default the image's |
| `[execution].image` | no | the container image the instance runs in |
| `[execution].name` | no | a different name for the instance's containers |
| `[environment]` | no | variables passed to the containers unchanged |

Unknown sections and keys are errors, so a misspelt key fails when the
file is read. Host settings (`[platform]`, `[cache]`, `[database]`)
belong in the system config, never in an application; see
[Configuration](configuration.md).

`[application].compose_files` adds services to the platform's own list.
An application that brings open-webui lists `webui`, and starting it
adds that service to the shared platform. Whether the host runs a GPU
worker is the host's decision, made in the system config.

`[execution].image` may carry a tag or a digest, and is then used as
written. An untagged image gets the platform's tag. The default is
`ghcr.io/bayinfosys/marigold-executor-python`.

Running straight from a directory, the directory name stands in for a
missing `name`.

## models.yaml

```yaml
_templates:
  model: &model
    provider: huggingface

models:
  - { <<: *model, name: qwen/qwen3-0.6b, type: instruct }
  - { <<: *model, name: sentence-transformers/all-minilm-l6-v2, type: text-embedding }
```

| Field | Meaning |
|---|---|
| `name` | the model's Hugging Face repository |
| `type` | the model type; every type is listed in [Model types](model-types.md) |
| `provider` | `huggingface` |
| `input`, `output` | optional; filled from the type when absent |

`_templates` holds YAML anchors for repeated fields. An application
lists as many model files as it needs:

```toml
[application]
models_yaml = ["models-instruct.yaml", "models-embed.yaml"]
```

Check a file without downloading anything:

```sh
marigold cache validate ./my-app
```

## What an instance can rely on

**Mounts**

| Path | Contents | Mode |
|---|---|---|
| `/app` | the application root; the working directory | read-only |
| `/outputs` | this application's own output directory | read-write |

`[execution].command` runs in `/app`.

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
application -- a web service, an agent loop -- runs until stopped.

**Never available**: the host filesystem beyond the two mounts, the
Docker socket, the platform database.

How to submit work and read results is in [API](api.md).

## Running while you develop

Install the application once and populate its models, then run the
working directory. The instance mounts whichever copy you start, so
edits take effect on the next start.

```sh
marigold cache init
marigold application create ./my-app -o /tmp
marigold application install /tmp/my-app-0.1.0.tar.gz
marigold cache populate my-app
marigold application start ./my-app
marigold application logs my-app
```

`application start` accepts an installed name, an application
directory, or an archive; the installed index is checked first. The
cache container reads `models.yaml` from the installed copy, so after
adding a model, reinstall and run `cache populate` again.

## Packaging

```sh
marigold application create ./my-app -o dist/
```

This writes `dist/my-app-0.1.0.tar.gz`. The same directory always
produces the same bytes, so the sha256 identifies the content.
Archives leave out version control, virtual environments, caches,
build output and `.env` files, and are written with ownership and
permissions stripped to read and execute.

Change `version` whenever the contents change. A registry publishes
whatever version the directory declares, and users compare versions to
know what they have.

`install` copies an archive to
`data/applications/_archives/<sha256>.tar.gz`, extracts it to
`data/applications/_src/<digest>/` and records it in
`data/applications/installed.json` under its name. `uninstall` removes
the index entry and the extracted tree; the archive stays, so a
reinstall is free, and the model cache is untouched.

## README

A README describes what the application does and what its directories
hold. Leave commands out: registry catalogue pages generate the install
commands for the version of Marigold that built them, so they stay
current.

## Not yet built

- Services supplied by the application: its own compose file, so an
  application with a web interface publishes its own port. See
  [Porting](porting.md#applications-with-a-web-interface).
- Model placeholders: `$name` in model fields, with defaults in `models.yaml` and overrides at start.
- Runs: a runs API, run records, and a handler interface for applications that serve many requests.
- `api.py`, served by the instance and reached through the platform API.
- Interpreted applications: Prompt and PromptLoop kinds defined by role files.
- An application database, requested like `webui`.
- Instance expansion: several containers from one application, parameterised by a list or a seed (`MARIGOLD_INSTANCE_SEED`), up to `max_count`.
- `--attach`, so `application start` returns the application's exit code.
- Limits on archive size and member count at extraction.
