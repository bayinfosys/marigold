---
title: Installing applications
description: Adding a registry, installing an application by name, downloading its models and running it.
nav_order: 5
---

# Installing applications

```sh
marigold registry add https://examples.marigold.run/
marigold application install platform-model-test
marigold cache populate platform-model-test
marigold application start platform-model-test
```

`registry add` records a registry in your system config. `install`
finds the application in your registries, downloads its archive,
checks it against the registry's index and installs it. `cache
populate` downloads the models it declares. `start` runs it.

## Choosing a version

```sh
marigold application install platform-model-test==0.3.0
marigold application install "platform-model-test>=0.3"
```

With no version, the highest release is installed. Installing another
version replaces the installed one.

## Dependencies

An application can use other applications, declared in its
`marigold.toml`:

```toml
[application]
requires = ["texture-forge>=0.2", "npc-voice>=0.1"]
```

`install` resolves each requirement through your registries and
installs it too. An installed version that satisfies the requirement
is kept. A requirement can name its registry, in which case that
registry must be in your list:

```toml
requires = ["https://demos.marigold.run/npc-voice>=0.1"]
```

## Several registries

```sh
marigold registry add https://apps.example.org/
marigold registry list
marigold registry remove https://apps.example.org/
```

Registries are searched in the order they were added. The first that
lists a name supplies it, so a registry further down the list can never
replace an application from one above it.

The list is `[registry] url` in the system config, and
`MARIGOLD_REGISTRY_URLS`, comma-separated, overrides it. Registries are
plain HTTP(S); Marigold sends no credentials.

## Models

```sh
marigold cache populate platform-model-test
```

Downloading models is always an explicit step: it is long and heavy,
and nothing else triggers it. Run it after installing, on a fast
connection or before going offline. An application whose models are
not cached starts, and its requests to the missing models fail.

Gated Hugging Face models need `HF_TOKEN` in the environment. A model
already in the cache is used as it is, by every application that
declares it. Uninstalling an application leaves the cache unchanged;
`cache populate --prune` removes cached models the given application
does not declare.

```sh
marigold cache inspect            # what is cached, sizes, location
marigold cache validate <name>    # check its models.yaml, no download
```

## Managing installed applications

```sh
marigold application list                  # name, version, registry
marigold application status <name>
marigold application logs <name>
marigold application stop <name>
marigold application uninstall <name>
```

`marigold app` is an alias for `marigold application`.

## What to check first

An application runs its own code in a container on your host, with
access to the platform API. The digest check confirms that the archive
is the one the registry lists. It says nothing about who wrote it.
Read the application's catalogue page and source before installing:
its models page shows every model it will download.
