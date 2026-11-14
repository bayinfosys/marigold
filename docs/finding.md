---
title: Finding applications
description: Registries, their catalogues, and the machine-readable index and llms.txt for tools and agents.
nav_order: 7
---

# Finding applications

A registry is a URL. Anyone can publish one: it is static files on
GitHub Pages or any web server, built with `marigold registry build`
([Publishing](publishing.md)).

## Registries

| Registry | Address | Holds |
|---|---|---|
| Marigold examples | [examples.marigold.run](https://examples.marigold.run/) | platform tests, benchmarks and small applications ([Examples](examples.md)) |
| Marigold demos | [demos.marigold.run](https://demos.marigold.run/) | applications built on the platform ([Showcase](showcase.md)) |

## Community registries

Registries published by people outside the project are listed here.
None are listed yet.

To add yours, open an issue on
[bayinfosys/marigold](https://github.com/bayinfosys/marigold/issues)
with the registry's URL and a one-line description.

## Who runs a registry

The same static files serve different purposes, depending on who runs
the registry and where it is reachable:

| Registry | Run by | Purpose |
|---|---|---|
| Public | a project or a person | applications for anyone to install |
| Internal | an organisation, on its own network | its own applications, for its own machines |
| Mirror | a security or platform team | re-published copies of vetted versions; listed first, it supplies every name it holds |
| Client | a consultancy or IT partner | applications built for, and delivered to, one client |
| Air-gapped | anyone | the registry files copied onto an isolated network |

A mirror supplies the versions it holds only to hosts that list it
first. A name the mirror lacks falls through to the next registry, a
requirement that names a registry URL fetches from that registry, and
`MARIGOLD_REGISTRY_URLS` overrides the configured list
([Installing](installing.md#several-registries)). Registries are plain
HTTP(S): an archive is checked against the sha256 in its registry's
index, and trust rests with whoever runs the host.

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
