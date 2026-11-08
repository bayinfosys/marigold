---
title: Documentation
description: Marigold documentation -- getting started, applications, registries, configuration, model types and the API.
nav_order: 0
---

# Documentation

This directory is the Marigold documentation.
It is read here on GitHub, and published at [marigold.run/docs](https://marigold.run/docs/).
A file with front matter is published; a file without it is not.

## Start

- [Getting started](GETTING-STARTED.md) -- install the CLI, run a first
  application, call the OpenAI-compatible endpoints.

## Applications

- [Applications](APPLICATIONS.md) -- what an application is, and the three layers it runs in.
- [Building](BUILDING.md) -- `marigold.toml`, `models.yaml`, the instance contract, packaging.
- [Publishing](PUBLISHING.md) -- registries, and publishing one with GitHub Pages or any static host.
- [Installing](INSTALLING.md) -- adding registries, installing by name, dependencies.
- [Finding](FINDING.md) -- registries, catalogues, and the index for tools and agents.
- [Examples](EXAMPLES.md) -- the examples registry.
- [Showcase](SHOWCASES.md) -- the showcase registry.

## Reference

- [Configuration](CONFIGURATION.md) -- the system config, output storage, authentication.
- [Model types](MODEL-TYPES.md) -- every model type, its input and output.
- [API](API.md) -- submitting and polling, binary outputs, the OpenAI-compatible endpoints.

## Design

- [Architecture](ARCHITECTURE.md) -- how the running system is divided, and what each part may touch.
- [Principles](PRINCIPLES.md) -- the reasoning behind recurring design decisions.
