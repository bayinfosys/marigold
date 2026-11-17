---
title: Deployment
description: Running Marigold from a laptop to your own cloud account -- the bundled platform, managed Postgres, GPU worker hosts and object storage on S3 or Azure.
nav_order: 13
---

# Deployment

Marigold is the same platform at every size. Applications do not change
between a laptop and a cloud account: only `marigold-host.toml` does --
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
# marigold-host.toml
[database]
url = "postgresql://marigold:<password>@db.example.internal:5432/marigold"
```

With a database URL set, the platform does not start its own Postgres.

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

```toml
# marigold-host.toml
[storage]
outputs = "s3"
bucket = "marigold-outputs"        # must already exist
region = "eu-west-2"
# endpoint = "http://..."          # an S3-compatible service; unset for AWS S3
```

On AWS, give the instances an IAM role with read and write on the
bucket rather than access keys.

**Azure Blob Storage:**

```toml
# marigold-host.toml
[storage]
outputs = "azure"
container = "marigold-outputs"     # must already exist
```

with `AZURE_STORAGE_ACCOUNT=<account>` in the shell environment.

On Azure, give the instances a managed identity with the Storage Blob
Data Contributor role on the container.

The worker writes outputs; the API only reads them. See
[Configuration](configuration.md) for every storage key and the
secrets each store reads from the shell.

## GPU worker hosts

Each worker host runs a worker against the shared database, with its
own model cache:

```toml
# marigold-host.toml on a worker host
[platform]
compose_files = ["cpu", "gpu"]      # a worker only: no API, no Postgres

[database]
url = "postgresql://marigold:<password>@db.example.internal:5432/marigold"

[storage]
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

## Restricting instances

Marigold limits what each container can use: memory, CPUs and
processes per service from `[resources]`, and hardened application
instances (see [Configuration](configuration.md#resource-limits)). It
leaves the network to the host. Both platform networks are ordinary
Docker bridges, so application instances can reach the internet.

To restrict that, use the host's own controls:

- a security group, network ACL or host firewall denying outbound
  traffic from the machine, with exceptions for model downloads and
  object storage;
- private endpoints (AWS VPC endpoints, Azure Private Link) for object
  storage and the database;
- Docker's `DOCKER-USER` iptables chain, for rules on container traffic
  alone.

`[network] bind` decides who reaches the API: `127.0.0.1`, the
default, admits this machine only; `0.0.0.0` admits any host on the
network, each trusted by its `X-User-Id`.

## Air gaps

Every shape can run without outbound access once the container images
and models are in place: mirror the images into your registry, populate
the model caches, and close the egress. Workers make no network calls
and load models only from their cache.

## Help

Bay Information Systems builds Marigold applications for clients, sets
up internal registries and mirrors, deploys the platform on a client's
own servers or cloud account, and works with design partners on what
the platform does next: see [Services](https://marigold.run/services.html).
