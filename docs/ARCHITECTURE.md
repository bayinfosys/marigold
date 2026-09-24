# Marigold -- Architecture

How the running system is divided, what each part may touch, and why.
The reasoning is in PRINCIPLES.md (principles 6 and 7); this document
describes the result.

---

## Three layers

**Platform.** Postgres, the API, the worker and the cache container.
One per host, shared by every application. Compose project `marigold`.
Configured entirely by the system config, so it starts, stops and
reports with no package in hand:

    marigold platform start
    marigold platform status
    marigold platform logs [service]
    marigold platform stop [--applications]

**Package.** A directory or archive holding `marigold.toml`, one or more
`models.yaml` files, and application code. Installed into the cache
under its name. See PACKAGES.md.

**Application.** A package's code running in its own container, compose
project `marigold-<application>`. Started, stopped and replaced without
touching the platform or any other application.

    marigold application start <package>
    marigold application status <package>
    marigold application logs <package>
    marigold application stop <package>

`application start` brings the platform up first when it is not already
running. Several applications share one platform; stopping one leaves
the others and the platform running.

---

## Two gateways

Two components face outward. Everything else is internal.

**The cache container** is the gateway for artefacts. It downloads
weights, reads installed packages, creates the platform's tables, and
writes the catalogue. It is the only component that needs outbound
network access, and the only one that writes the model cache.

**The API** is the gateway for requests. Applications and external
clients submit work, poll results, and read the catalogue through it.
It is the only component on both networks, and the place
authentication will live.

The worker talks to Postgres and reads the cache. It makes no outbound
calls: `HF_HUB_OFFLINE` is set, and the cache is mounted read-only.

---

## Networks

| Network | Members | Purpose |
|---|---|---|
| `marigold-core` | postgres, worker, cache-init, api | platform internals |
| `marigold-applications` | api, every application executor | the only route from an application to the platform |

Postgres publishes no port on the host. Containers on `marigold-core`
reach it as `postgres:5432`; nothing else can. For a shell:

    docker compose -p marigold exec postgres psql -U marigold

The API publishes port 8000 on the host for external clients.

Both networks are created by the platform's compose file with fixed
names, and joined as external by the executor's, which is how two
compose projects share them.

---

## Mounts

| Host path (under the cache root) | cache-init | worker | api | executor |
|---|---|---|---|---|
| `data/models` | read-write | read-only | -- | -- |
| `data/applications` | read-only (`/applications`) | -- | -- | -- |
| `data/applications/_src/<digest>` | via the above | -- | -- | read-only (`/app`) |
| `data/applications/<name>/outputs` | -- | -- | -- | read-write (`/outputs`) |
| `data/outputs`, `data/tmp` | -- | read-write | -- | -- |
| `data/postgres` | -- | -- | -- | -- (postgres only) |
| `data/packages` | -- | -- | -- | -- (CLI only) |

The CLI, on the host, writes `data/packages` (archives and the installed
index) and `data/applications/_src` (extracted packages). `marigold cache
init` creates the layout with the invoking user's ownership; directories
Docker creates for a bind mount are owned by root.

---

## Access model

Each component owns what it writes. The table is the design; roles and
per-component DSNs are not yet enforced, so today every component
connects as the same Postgres user.

| Table | cache-init | worker | api |
|---|---|---|---|
| catalogue | write | read | read |
| queue tables | create | read, update, delete | insert, read |
| results, usage | create | write | read |
| workers | create | write | -- |

Table creation belongs to the cache container, which runs before
anything is served on every platform start. The worker still creates
three tables of its own at startup; that is the one remaining
exception, recorded in TODO.md.

Model failure state (`failed_reason`) is written by the worker onto the
catalogue row today. Under enforced roles it moves to a table the
worker owns, so the catalogue stays a record of cache contents.

---

## The catalogue

A catalogue row means a model's weights are in the cache. `marigold
cache populate <package>` reads the package's models.yaml inside the
cache container, downloads what is missing, and registers each model as
its weights are confirmed: queue first, then row. A model that fails to
download gets no row.

The catalogue is host-wide. Rows accumulate across packages and are
never removed by uninstalling one: a cached model stays available to
every application.

The API answers accordingly:

| Response | Meaning |
|---|---|
| 400 unknown model | not in the catalogue: not cached, or never declared |
| 409 model load failed | cached, but the worker could not load it |
| 503 | platform tables not yet created |

---

## Failure containment

A model that fails to download is reported by `cache populate` and gets
no row; every other model proceeds. A model that fails to load is
marked by the worker, its queue drained with errors, and further
submissions rejected with 409; the worker moves on. An application that
fails exits in its own container; the platform and other applications
are unaffected. An application whose platform stops keeps running and
fails its API calls, visibly, in its own logs.

---

## Scaling

The worker serves one model at a time, choosing the deepest queue on
each sweep. Several applications sharing one worker queue behind one
another, which is how a fleet of agents runs on a single local GPU.
Queue claims use `SELECT ... FOR UPDATE SKIP LOCKED`, so adding workers
is safe at the message level; assigning models to specific workers is
future work, recorded in TODO.md.

---

## Known gaps

- Postgres roles per component are designed and not enforced.
- The worker still creates its own tables at startup.
- `marigold-core` has a route out; making it internal needs the cache
  container on a separate egress network.
- Package archives are extracted with `filter="data"` and no limit on
  uncompressed size or member count.
- The system config is found relative to the working directory before
  the home directory, so changing directory can change which cache and
  platform the CLI addresses.
