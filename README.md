# Marigold

[![PyPI](https://img.shields.io/pypi/v/bayis-marigold)](https://pypi.org/project/bayis-marigold/)
[![GitHub tag](https://img.shields.io/github/v/tag/bayinfosys/marigold)](https://github.com/bayinfosys/marigold/tags)

A package manager and runtime for local AI applications. One
self-hosted model layer serves every application on the machine:
applications install by name from registries, share one model cache
and one GPU queue, and reach models through a typed API with
OpenAI-compatible chat and embeddings.

Underneath, typed operations -- a capability class, a model and an
input set -- produce immutable results that applications compose.

Marigold runs as three separate layers on one host:

- **the platform** -- a model cache, a catalogue, a worker and an API,
  shared by everything on the host;
- **applications** -- a list of required models plus the code that uses
  them, installed into the cache by name;
- **instances** -- an application's code running in its own container,
  reaching the platform only through the API.

Applications hold no weights. Many instances share one model cache and
one worker, which is what lets a fleet of agents run on a single local
GPU and the same application run unchanged on larger hardware.

The documentation is in [docs/](docs/README.md), and published at
[marigold.run/docs](https://marigold.run/docs/).

## Status

Early stage. The interfaces an application is written against --
`marigold.toml` and `models.yaml`, the instance contract, the API
routes and the registry index (`protocol: 1`) -- are stable; see
[What is stable](docs/applications.md#what-is-stable). The CLI and the
configuration format may change. Issues and questions are welcome; for a pull request, open an
issue first to discuss the change before writing code.

## Prerequisites

- Docker and Docker Compose
- NVIDIA Container Toolkit, for a GPU worker
- Python 3.12, for the `marigold` command
- A Hugging Face token, for gated models

## Quickstart

<!-- The marigold.run home page renders this block. Keep it to commands. -->
```sh
pip install bayis-marigold
marigold cache init
marigold registry add https://examples.marigold.run/
marigold application install chat
marigold cache populate chat
marigold application start chat
```

`registry add` records the examples registry. `install` fetches the
`chat` application from it. `cache populate` downloads the models it
declares; this is the long step. `start` brings the platform up and
runs the application: Open WebUI at `http://localhost:3000`, backed by
a local instruct model. The walkthrough is in
[Getting started](docs/getting-started.md).

## Documentation

| | |
|---|---|
| [Getting started](docs/getting-started.md) | install, first application, OpenAI-compatible client |
| [Applications](docs/applications.md) | what an application is; [building](docs/building.md), [publishing](docs/publishing.md), [installing](docs/installing.md), [finding](docs/finding.md) |
| [Examples](docs/examples.md), [Showcase](docs/showcase.md) | the project's registries |
| [Porting](docs/porting.md) | bringing an existing AI application to Marigold |
| [Configuration](docs/configuration.md) | system config, registries, output storage, authentication |
| [Deployment](docs/deployment.md) | from a laptop to your own cloud account |
| [Model types](docs/model-types.md) | every type, route, input and output; adding a type |
| [API](docs/api.md) | submit and poll, binary outputs, OpenAI-compatible endpoints |
| [Architecture](docs/ARCHITECTURE.md), [Principles](docs/PRINCIPLES.md) | how the system is divided, and why |

## Repository structure

```
package/src/
  api/                  FastAPI application; routes/ is a package
  models/               model handlers, one file per model type
  shared/               enums, registry, database, outputs, usage
  cli/                  the `marigold` command
    main.py             parser
    commands.py         command implementations
    config.py           system and application TOML, with provenance
    paths.py            the cache layout
    archives.py         writing and extracting application archives
    applications.py     identity, installation, resolution
    compose.py          compose projects, environment, invocation
  compose/              compose files and the multi-stage Dockerfile
  tools/
    cache_cli.py        the cache container's entrypoint
    model_cache_shared.py  cache providers
```

Example applications live in [marigold-examples](https://github.com/bayinfosys/marigold-examples),
published as the registry at [examples.marigold.run](https://examples.marigold.run/).
