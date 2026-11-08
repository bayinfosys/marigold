---
title: Getting started
description: Install the marigold CLI, start a self-hosted platform with Docker Compose, install an application from a registry, cache its models and run it.
nav_order: 1
---

# Getting started

This guide goes from nothing installed to a running application: a
shared model cache, an API and a worker on your own hardware, started
with Docker Compose, and an application installed from a registry.

## Prerequisites

- Docker and Docker Compose
- NVIDIA Container Toolkit, for a GPU worker
- Python 3.12, for the `marigold` command
- A Hugging Face token, for gated models such as anything under
  `meta-llama`. This guide needs none.

## Install the CLI

```sh
pip install bayis-marigold
marigold --version
```

Model code runs in containers, pulled the first time they start.

## One directory holds everything

Every piece of state Marigold keeps -- model weights, the database,
installed applications, outputs -- lives under one cache directory. No
named volumes, no external database, no state held only inside a
container.

Set its location in the system config:

```toml
# ~/.marigold/config.toml
[platform]
compose_files = ["core", "cpu"]     # ["core", "gpu"] for an NVIDIA worker

[cache]
dir = "/data/marigold"              # default: ~/.marigold/cache
```

The CLI reads `$MARIGOLD_CONFIG` if set, then `config.toml` in the
current directory, then `~/.marigold/config.toml`. Keep one config in
your home directory and set `MARIGOLD_CONFIG` in scripts. The full
format is in [Configuration](configuration.md).

Create the layout:

```sh
marigold cache init
```

For a cache under a system path such as `/data`, `cache init` prints
the two commands that create it with your ownership.

```
/data/marigold/data/
  models/          downloaded weights, shared by every application
  postgres/        the platform database
  applications/    installed applications and each one's outputs
  outputs/         binary inference outputs
  tmp/             worker offload space
```

## Install an application

```sh
marigold registry add https://examples.marigold.run/
marigold application install platform-model-test
marigold application list
```

`registry add` records the examples registry in your system config.
`install` finds `platform-model-test` there, downloads its archive,
checks it against the registry's index and installs it under its name.
[Installing](installing.md) covers versions, dependencies and several
registries.

## Download its models

```sh
marigold cache populate platform-model-test
```

The cache container reads the application's `models.yaml`, downloads
each model the cache lacks, and registers each one in the catalogue as
soon as its weights are present. This is the long, heavy step, and it
is always run explicitly: nothing else downloads models. A model that
fails to download is reported and skipped; the others proceed.

## Run it

```sh
marigold application start platform-model-test
marigold application logs platform-model-test
```

`start` brings the platform up if it is not already running -- Postgres,
the API, the worker and the cache container, as compose project
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

## Stopping

```sh
marigold application stop platform-model-test   # the application only
marigold platform stop --applications           # everything
```

Several applications share one platform. Stopping one leaves the
platform and the others running.

## Starting over

The model cache is expensive to rebuild and safe to keep. To reset
everything else:

```sh
marigold platform stop --applications
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
