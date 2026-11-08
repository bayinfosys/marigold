---
title: Deployment
description: Running Marigold from a laptop to your own cloud account -- the bundled platform, managed Postgres, GPU worker hosts and object storage on S3 or Azure.
nav_order: 13
---

# Deployment

Marigold is the same platform at every size. Applications do not change
between a laptop and a cloud account: only the system config does --
where the database is, where outputs are stored, and where the workers
run. In every shape the data stays on infrastructure you control.

## Three shapes

| Shape | Database | Workers | Outputs |
|---|---|---|---|
| Laptop or home box | the bundled Postgres | the local GPU or CPU | the cache directory |
| Startup | a managed Postgres such as Supabase | one or more rented GPU instances | an S3 bucket |
| Institution | AWS RDS or Azure Database for PostgreSQL, in your own account | GPU instances in your own account | S3 or Azure Blob Storage, in your own account |

## The parts

| Part | What it holds | Where it can run |
|---|---|---|
| Database | the job queue, results, the model catalogue, usage | the bundled Postgres, or any Postgres 17 |
| API | the HTTP entry point for applications and clients | beside the database, or anywhere that reaches it |
| Workers | model execution, one model loaded at a time per worker | any host with a GPU, or a CPU, that reaches the database |
| Model cache | downloaded weights | one per worker host |
| Object storage | images, audio and video outputs | the cache directory, S3, or Azure Blob Storage |

Workers take jobs from the queue in the database. Adding a GPU host adds
a worker; nothing else changes, and applications see more throughput.

## Laptop or home box

The default: everything under one cache directory, started by
`marigold application start`. See [Getting started](getting-started.md).

## External database

Point every host at the same Postgres:

```toml
# system config
[database]
url = "postgresql://marigold:<password>@db.example.internal:5432/marigold"
```

`MARIGOLD_DATABASE_URL` in the environment overrides it. With a database
URL set, the platform does not start its own Postgres.

Managed services that work as they are:

- **Supabase**, for a small team: use the direct connection string, not
  the transaction pooler, since workers hold long-lived connections.
- **AWS RDS for PostgreSQL**, in your own VPC.
- **Azure Database for PostgreSQL**, flexible server, in your own
  virtual network.

Keep the database private to the network the API and workers run in.

## Object storage

Outputs go to the cache directory by default. For several hosts, use a
bucket every host can reach.

**S3, or any S3-compatible service:**

```sh
MARIGOLD_STORAGE=s3
MARIGOLD_STORAGE_BUCKET=marigold-outputs     # must already exist
MARIGOLD_STORAGE_ENDPOINT=                   # unset for AWS S3
AWS_DEFAULT_REGION=eu-west-2
```

On AWS, give the instances an IAM role with read and write on the
bucket rather than access keys.

**Azure Blob Storage:**

```sh
MARIGOLD_STORAGE=azure
MARIGOLD_STORAGE_CONTAINER=marigold-outputs   # must already exist
AZURE_STORAGE_ACCOUNT=<account>
```

On Azure, give the instances a managed identity with the Storage Blob
Data Contributor role on the container.

The worker writes outputs; the API only reads them. See
[Configuration](configuration.md) for every storage variable.

## GPU worker hosts

Each worker host runs a worker against the shared database, with its
own model cache:

```toml
# system config on a worker host
[platform]
compose_files = ["cpu", "gpu"]      # a worker only: no API, no Postgres

[database]
url = "postgresql://marigold:<password>@db.example.internal:5432/marigold"

[cache]
dir = "/data/marigold"
```

Populate each host's cache with the models it should serve, then start
it:

```sh
marigold cache populate <application>
marigold platform start
```

A host serves the models in its own cache. Hosts with different GPUs
can hold different models: large instruct models on the large cards,
embeddings and evals on smaller ones.

## The API host

The API host runs `["core"]` with the same `[database]` and storage
settings, and no worker. Applications run beside it, or on any host
that reaches it.

Marigold has no authentication of its own. Outside a private network,
put your own in front of the API -- a reverse proxy, a load balancer
with your identity provider -- and have it set `X-User-Id` for each
caller. See [Configuration](configuration.md#authentication).

## Air gaps

Every shape can run without outbound access once the container images
and models are in place: mirror the images into your registry, populate
the model caches, and close the egress. Workers make no network calls
and load models only from their cache.

## Help

Bay Information Systems helps organisations deploy Marigold in their own
cloud accounts, and works with design partners on what the platform does
next: see [Support and design partners](https://marigold.run/pricing.html).
