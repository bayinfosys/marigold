# Workplan 2026-11-19: model configuration and monitoring

## Goal

Run the Grasmere chat and evals applications end to end on a host with
two 12 GB GPUs, publish the blog post from that run, and give an
operator one command that shows why a model does not load.

## Background

The first Grasmere run (2026-11-18) found:

- the worker ran on the CPU: compose_files lacked "gpu"; "gpu" is an
  overlay on "cpu" and needs both
- a CPU chat request took 502s; the API waits 300s and returned 504,
  discarding the result
- Open WebUI added 13 tool definitions and background tasks, turning
  one greeting into 5163 input tokens
- Grasmere E4B is 15.9 GB in bf16 and does not fit across two 12 GB
  cards; 4-bit is required
- LOAD_IN_4BIT could only be set per model in the application's
  models.yaml; the host had no say
- a failed model stayed failed: populate carried the mark over, and
  the results cache served the stored error for identical requests
- failure messages contained only the model name
- a YAML boolean in extra_env crashed the whole worker
- platform stop removed the applications network under a stopped
  executor, which then failed to start
- load events went to a no-op backend; nothing records model history

## Principles

- smallest possible change; when new functionality needs a lot of
  code, propose a refactoring that keeps the logic simple
- few CLI commands and parameters; two existing commands in
  preference to a new one
- no fallbacks or compatibility code; breaking changes are acceptable
- the host config is authoritative; the host overrides the application
- every write goes through the maintainer: patches are reviewed and
  applied by hand
- no tests while interfaces are changing

## Tasks

Each task is one patch: GOAL.md states the change and its effects,
BREAKDOWN.md the work in order, output.patch the change itself.

| Task | Goal                                         | Release |
|------|----------------------------------------------|---------|
| 0000 | worker load failures                         | 0.8.3   |
| 0001 | catalogue failures and the results cache     | 0.8.3   |
| 0002 | platform stop, compose checks, verify        | 0.8.3   |
| 0003 | model settings in models.yaml                | 0.8.3   |
| 0004 | host model settings                          | 0.8.3   |
| 0005 | grasmere-chat v0.0.3                         | -       |
| 0006 | marigold-examples settings                   | -       |
| 0007 | stored lifecycle events                      | 0.8.4   |
| 0008 | model detail from the API                    | 0.8.4   |
| 0009 | marigold models inspect                      | 0.8.4   |
| 0010 | model usage summary                          | 0.8.4   |
| 0011 | data directories and reset                   | 0.8.4   |

## Order

    0000 -> 0001 -> 0002 -> 0003 -> 0004 -> release 0.8.3
      -> 0005 (grasmere-chat), 0006 (marigold-examples)
      -> Grasmere run and blog post
    0007 -> 0008 -> 0009 -> 0010 -> 0011 -> release 0.8.4

0.8.3 follows 0004 so the blog shows host settings
(`[models] load_in_4bit = true`), and the application repositories
move to `settings:` once, against a released marigold.

## Decisions

- the host overrides the application for model settings
- ModelSettings: typed fields for the loader keys, extra keys allowed;
  a setting's name is its environment variable in lower case
- host model settings at three levels: global, type, name
- no admin routes; the API is assumed authenticated and access is
  controlled at the infrastructure layer
- events accumulate with no TTL
- MARIGOLD_MODEL_SETTINGS carries the host [models] table into the
  containers; it is not an override. A different host config is the
  way to run with different settings, so the host file stays
  authoritative over the shell
- platform stop always stops applications first; the --applications
  flag goes
- cache populate clears a model's failure; no reset command
- the steps to check a change go in its patch's commit message

## Open

- cache-init downloads by loading each model through its handler, so
  it needs the same settings as the worker and reads full weights into
  memory. Downloading with huggingface_hub.snapshot_download would
  remove settings from cache-init. Cost: whole repositories fetched
  unless the type spec gives allow_patterns; handlers that pull further
  repositories at load need those listed. Accepted, this becomes a
  task before 0003; declined, 0004 also passes host settings to
  cache-init with 4-bit forced off there.

## Removed

- multi-GPU model placement
- --force-recreate on application start (replaced by the platform
  stop change)
- marigold platform reset (documented as existing commands, 0011)
- marigold models reset (cache populate clears failures)
- shell versus host-file precedence (closed: the file is authoritative)

## Backlog

- single marigold package (marigold/core, cli, api, models, backend,
  compose); reconsider if commands.py becomes hard to follow
- streaming for /v1/chat/completions, so a slow request does not end
  in a 504
- application, execution and run reference types
- /v1/models listing failed models
