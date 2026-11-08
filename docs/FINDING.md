---
title: Finding applications
description: Registries, their catalogues, and the machine-readable index and llms.txt for tools and agents.
nav_order: 6
---

# Finding applications

A registry is a URL. Anyone can publish one, and there is no central
directory yet.

## Registries

| Registry | Address | Holds |
|---|---|---|
| Marigold examples | [examples.marigold.run](https://examples.marigold.run/) | platform tests, benchmarks and small applications ([Examples](examples.md)) |
| Marigold demos | [demos.marigold.run](https://demos.marigold.run/) | applications built on the platform ([Showcase](showcase.md)) |

## What a catalogue shows

Each application has two pages:

- **The application page:** its README, version, archive, sha256,
  source links and install commands.
- **The models page:** every model it declares, with type and provider,
  each linked to its Hugging Face model card, plus the `models.yaml`
  as written.

The models page gives a quick sense of what an application needs to
run: how many models, of which types, and through the model cards, how
large they are.

## From the command line

```sh
marigold application search rag
```

searches the names and descriptions of every application in your
registries, and prints each match with its version, description and
registry. `marigold registry list` shows which registries are searched,
in order.

## For tools and agents

Every registry publishes:

| File | Contents |
|---|---|
| `marigold-applications.json` | the index: every application, version, archive and sha256 |
| `llms.txt` | the registry, its install commands and its applications, as plain text |
| `sitemap.xml` | every catalogue page, for search engines |

Every catalogue page also links to the index from its HTML head, and
carries schema.org `SoftwareApplication` data.
