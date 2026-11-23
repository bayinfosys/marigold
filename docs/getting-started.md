---
title: Getting started
description: Install the marigold CLI, start a self-hosted platform with Docker Compose, install an application from a registry, cache its models and run it.
nav_order: 1
---

# Getting started

This guide goes from nothing installed to a running application: this involves 
creating a shared model cache, an API and a worker on your own hardware, started
with Docker Compose, and an application installed from a registry.

## Prerequisites

- Docker and Docker Compose
- NVIDIA Container Toolkit, for a GPU worker
- Python 3.12 and pipx or uv, for the `marigold` command
- A Hugging Face token, for gated models such as anything under
  `meta-llama`. (not required for this guide)

## Install the CLI

Install the library into an environment with pipx:

```sh
pipx install bayis-marigold
marigold --version
```

or with uv:

```sh
uv tool install bayis-marigold
marigold --version
```

When the default Python is older than 3.12, add `--python python3.12`
to `pipx install`, or `--python 3.12` to `uv tool install`.

| | pipx | uv |
|---|---|---|
| upgrade | `pipx upgrade bayis-marigold` | `uv tool upgrade bayis-marigold` |
| remove | `pipx uninstall bayis-marigold` | `uv tool uninstall bayis-marigold` |

Model code runs in containers, pulled the first time they start.

## The marigold state directory

Every piece of state Marigold keeps -- model weights, the database,
installed applications, outputs -- lives under one cache directory.
No named volumes, no external database.

This location defaults to `~/.marigold.cache`.

NB: this directory can become very large with model weights downloads.
We recommend a separate drive or mount to avoid running out of disk.

It is set in `marigold-host.toml`:

```toml
# ~/.marigold/marigold-host.toml
[platform]
compose_files = ["core", "cpu"]     # ["core", "cpu", "gpu"] for an NVIDIA worker

[storage]
location = "/data/marigold"              # default: ~/.marigold/cache
```

Host config location is set, in order of priority:
+ `--host-config PATH` parameter to the cli,
+ `$MARIGOLD_HOST_CONFIG` environment variable, then
+ `marigold-host.toml` in the current directory, then
+ `~/.marigold/marigold-host.toml` in your `$HOME` directory.

Keep one file in your home directory and set `MARIGOLD_HOST_CONFIG` in scripts.

Host file keys are described in [Configuration](configuration.md).

Create the directory layout on disk with:

```sh
marigold cache init
```

This will create the following tree structure with your current user as owner:

```
/data/marigold/data/
  models/          downloaded weights, shared by every application
  postgres/        the platform database
  applications/    installed applications and each one's outputs
  outputs/         binary inference outputs
  tmp/             worker offload space
```

NB: ensure these directories are created; we force docker to fail if directories do not exist.

## Install an application

Marigold applications are small packages installed from remote registries.
You must add the registry initially.

```sh
marigold registry add https://examples.marigold.run/
marigold application install platform-model-test
marigold application list
```

`registry add` records the examples registry in `marigold-host.toml`.
`install` finds `platform-model-test` there, downloads its archive,
checks it against the registry's index and installs it under its name.
[Installing](installing.md) covers versions, dependencies and several
registries.

## Download model weights

```sh
marigold cache populate platform-model-test
```

The cache container reads the application's `models.yaml`, downloads
each model to the cache, and registers each one in the catalogue.
This is a long, heavy step, and it is always run explicitly;
there is no other way to download model weights.
A model that fails to download is reported and skipped.
Models in a `models.yaml` file may be altered so models can be replaced.

## Run the application

```sh
marigold application start platform-model-test
marigold application logs platform-model-test
```

`start` brings the platform up if it is not already running -- Postgres,
the API, the worker and the cache container, as compose project called
`marigold` -- then runs the application in its own container. The API
answers at `http://localhost:8000/docs`.

`platform-model-test` sends one request to each catalogued model and
prints a line per model. The first requests are slow while each model
loads. When it has finished:

```sh
marigold application status platform-model-test
```

shows its exit code: 0 if every model answered.

## Call it from your own code

The platform answers on OpenAI-compatible endpoints, so an unmodified
OpenAI SDK client works against it:

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000/v1", api_key="unused")
model = client.models.list().data[0].id
reply = client.chat.completions.create(
    model=model,
    messages=[{"role": "user", "content": "Say hello."}],
)
print(reply.choices[0].message.content)
```

No API key is checked. The native API and the full list of endpoints
are in [API](api.md).

## When a model fails

```sh
marigold models inspect
marigold models inspect qwen/qwen3-8b
```

With no name, `models inspect` lists the catalogue: each model's name,
type, status and the application that declared it. With a name, it
prints the model's settings and where each came from, its status and
failure reason, its last load -- the worker, footprint, dtype and the
bytes on each device -- a summary of its usage, and its recent events. Everything comes from
the API at the address in `[network]`, so it reads any platform that
address reaches. `marigold cache inspect <name>` gives the same model's
files on disk.

A model that fails to load is marked failed, and the API answers its
requests with 409 and the reason. The reason names the cause: a model
too large for the GPUs, for example, shows the tensors left off the GPU
and the free memory of each device. Settings such as 4-bit quantisation
can be changed on the host without touching the application; see
[Model settings](configuration.md#model-settings). Then:

```sh
marigold cache populate <application>
```

rewrites the application's catalogue rows, which clears the failure,
and the next request loads the model again.

## Stopping

```sh
marigold application stop platform-model-test   # the application only
marigold platform stop                          # every application, then the platform
```

Several applications share one platform. Stopping one leaves the
platform and the others running.

## Starting over

The model cache is expensive to rebuild and safe to keep. To reset
everything else:

```sh
marigold platform stop
sudo rm -rf /data/marigold/data/postgres
```

The next start creates a fresh database, and `cache populate`
re-registers cached models without downloading them again. Deleting
`data/models` as well removes every downloaded weight.

## Running air-gapped

Once `cache populate` has run, every model an application needs is on
local disk. The worker makes no network calls and loads only from the
cache. With the container images pulled and the models populated, the
host can be disconnected entirely.

## Next

- [Building](building.md) an application of your own.
- The [Examples](examples.md) registry: platform tests, benchmarks and
  small applications to start from.
