---
title: Applications
description: What a Marigold application is, and how applications are built, published, found and installed.
nav_order: 2
---

# Applications

A Marigold application is a declared set of models plus the code that
uses them, packaged as one archive and run against a shared platform.
It is a directory holding:

- `marigold.toml`: the application's name, version and how it runs;
- one or more `models.yaml` files: the models it uses;
- its code, data and a `README.md`.

An application holds no model weights. The platform downloads the
declared models into a cache shared by every application on the host.

## Three layers

| Layer | What it is | How many |
|---|---|---|
| Platform | model cache, catalogue, worker and API | one per host |
| Application | an archive installed into the cache by name | any number |
| Instance | an application's code running in its own container | one or more per application |

An instance reaches the platform only through the API. Many instances
share one cache and one worker, which is what lets a set of
applications run on a single local GPU, and the same application run
unchanged on larger hardware.

## What applications are for

Anything that drives models through the API:

- an agent loop around an instruct model;
- a document pipeline: extract text, embed, classify, summarise;
- a benchmark that records timing, tokens and power per request;
- a conformance test for the platform itself.

Models are not limited to text: see [Model types](model-types.md).

## From source to running

| Step | Command | Page |
|---|---|---|
| Write the application | `marigold.toml`, `models.yaml`, code | [Building](building.md) |
| Package it | `marigold application create` | [Building](building.md) |
| Publish a registry | `marigold registry build`, GitHub Actions | [Publishing](publishing.md) |
| Find applications | `marigold application search`, a catalogue | [Finding](finding.md) |
| Install one | `marigold application install <name>` | [Installing](installing.md) |
| Download its models | `marigold cache populate <name>` | [Installing](installing.md) |
| Run it | `marigold application start <name>` | [Installing](installing.md) |
