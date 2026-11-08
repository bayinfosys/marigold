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

- [Getting started](getting-started.md) -- install the CLI, run a first
  application, call the OpenAI-compatible endpoints.

## Applications

- [Applications](applications.md) -- what an application is, and the three layers it runs in.
- [Building](building.md) -- `marigold.toml`, `models.yaml`, the instance contract, packaging.
- [Porting](porting.md) -- bringing an existing AI application to Marigold.
- [Publishing](publishing.md) -- registries, and publishing one with GitHub Pages or any static host.
- [Installing](installing.md) -- adding registries, installing by name, dependencies.
- [Finding](finding.md) -- registries, catalogues, and the index for tools and agents.
- [Examples](examples.md) -- the examples registry.
- [Showcase](showcases.md) -- the showcase registry.

## Reference

- [Configuration](configuration.md) -- the system config, output storage, authentication.
- [Deployment](deployment.md) -- from a laptop to your own cloud account: managed Postgres, GPU worker hosts, S3 and Azure storage.
- [Model types](model-types.md) -- every model type, its input and output.
- [API](api.md) -- submitting and polling, binary outputs, the OpenAI-compatible endpoints.

## Design

- [Architecture](architecture.md) -- how the running system is divided, and what each part may touch.
- [Principles](principles.md) -- the reasoning behind recurring design decisions.
