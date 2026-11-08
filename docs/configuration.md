---
title: Configuration
description: The Marigold system config, where it is read from, registries, output storage and authentication.
nav_order: 12
---

# Configuration

Two layers of TOML. The system config holds host settings:
`[platform]`, `[cache]`, `[database]` and `[registry]`. Each
application's `marigold.toml` declares what the application is and
runs; its format is in [Building](building.md). An application config
that sets a host section is rejected. Where both layers set
`[environment]` values, the application's win per key.

## Where it is read from

The system config is `$MARIGOLD_CONFIG` if set, otherwise `config.toml`
in the current directory, otherwise `~/.marigold/config.toml`. Because
of the second rule, changing directory can change which config is used;
set `MARIGOLD_CONFIG` in scripts.

```sh
marigold config path          # the system config in use
marigold config show [name]   # every resolved value and the layer it came from
```

## The system config

```toml
[platform]
compose_files = ["core", "cpu"]    # add "gpu" for an NVIDIA worker: ["core", "cpu", "gpu"]
# tag = "0.8.1"                    # default: the installed CLI's version

[cache]
dir = "/data/marigold"             # default: ~/.marigold/cache

[database]
url = "postgresql://..."           # default: the platform's own Postgres

[registry]
url = ["https://examples.marigold.run/"]   # searched in order
```

`[registry] url` is written by `marigold registry add` and searched in
order; the first registry that lists a name supplies it.
`MARIGOLD_REGISTRY_URLS`, comma-separated, overrides it. See
[Installing](installing.md).

## Output storage

Images, audio and video are stored as objects and served by the API at
`GET /output/{mode}/{task}/{message_id}/{field}`. The store is set by
environment variables, read by the worker and the API:

```sh
MARIGOLD_STORAGE=fs                   # default: files under the cache's data/outputs
MARIGOLD_STORAGE=s3                   # any S3-compatible service
MARIGOLD_STORAGE_BUCKET=marigold      # s3: the bucket must already exist
MARIGOLD_STORAGE_ENDPOINT=http://...  # s3: unset means AWS S3
AWS_ACCESS_KEY_ID=...                 # s3: standard AWS variables
AWS_SECRET_ACCESS_KEY=...
AWS_DEFAULT_REGION=...
```

For Azure Blob Storage:

```sh
MARIGOLD_STORAGE=azure
MARIGOLD_STORAGE_CONTAINER=marigold   # the container must already exist
AZURE_STORAGE_ACCOUNT=...             # credentials from a managed identity, or
AZURE_STORAGE_CONNECTION_STRING=...   # a connection string
```

Set them in the shell profile: every `marigold` command reads them. For
several hosts sharing one store, see [Deployment](deployment.md).

## Authentication

Marigold has no authentication of its own. The caller is identified by
an optional `X-User-Id` header, defaulting to `local-user`, and that
header is trusted as received.

On localhost or a private network this needs nothing further. To expose
the API beyond that boundary, put the deployment's own authentication
in front of it -- a reverse proxy, a cloud load balancer, an identity
provider -- and have it set `X-User-Id` for each authenticated caller.
