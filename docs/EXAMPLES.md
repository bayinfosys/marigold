---
title: Examples
description: "The Marigold examples registry: platform tests, benchmarks and small applications to start from."
nav_order: 7
---

# Examples

The Marigold project keeps a registry of example applications beside
the platform. They test a new host, measure hardware, and show the
smallest useful applications, each one a starting point for your own.

```sh
marigold registry add https://examples.marigold.run/
marigold application search
```

The registry's catalogue is at [examples.marigold.run](https://examples.marigold.run/),
and its source at [github.com/bayinfosys/marigold-examples](https://github.com/bayinfosys/marigold-examples).

## Platform tests

| Application | What it checks |
|---|---|
| `control-plane-test` | the platform itself: the API, the catalogue, the job queue and the database behind them |
| `platform-model-test` | model execution: one small model of each type through the native API, the OpenAI-compatible endpoints, binary outputs and a deliberate download failure |
| `tool-call-conformance` | tool calling through the OpenAI-compatible endpoint, against every instruct model in the catalogue |

On a new host, run `control-plane-test` first: it is fast and downloads
almost nothing. Then run `platform-model-test` to exercise every model
type.

## Benchmarks

| Application | What it measures |
|---|---|
| `benchmark-llm` | every instruct model in a deployment: time, tokens, VRAM and power per response |
| `benchmark-image-gen` | image generation across models and settings |
| `benchmark-vid-gen` | video generation |

```sh
marigold application install benchmark-llm
marigold cache populate benchmark-llm
marigold application start benchmark-llm
marigold application logs benchmark-llm
```

Each request's identifier is a hash of its contents, so a re-run only submits work not already completed.

## Small applications

| Application | What it does |
|---|---|
| `chat` | a chat interface over your local models, with retrieval from uploaded documents |
| `simple-rag` | question answering over a folder of documents |
| `scraper` | a browser-driven collection pipeline with its own container image |

## Where to start

| You want to | Start with |
|---|---|
| check a new host | `control-plane-test`, then `platform-model-test` |
| choose a GPU | `benchmark-llm` |
| write your first application | `simple-rag`: copy the directory, rename it in `marigold.toml`, change its models |
| see more ambitious applications | the [Showcase](showcase.md) |
