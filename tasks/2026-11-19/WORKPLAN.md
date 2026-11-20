# Workplan 2026-11-19: model configuration and monitoring

## Goal

A host loads models that need host-specific settings, such as
Grasmere E4B in 4-bit on two 12 GB GPUs, without changing the
application that declares them; and an operator sees why a model does
not load.

## Context

The code these tasks touch, under package/src/:

- host config: cli/host_config.py; HostConfig is the source of truth
  and compose_env() is the only route to compose variables;
  docs/configuration.md is generated from it by scripts/config_doc.py
- compose files: compose/docker-compose.{core,cpu,gpu,webui}.yaml;
  "gpu" is an overlay on "cpu"
- CLI: cli/main.py (parser), cli/commands.py (commands)
- catalogue: each models.yaml entry becomes a ModelCatalogueItem
  (shared/db_models.py) in the model_catalogue table; `marigold cache
  populate <application>` writes the rows through cache-init
  (tools/cache_cli.py, tools/model_cache_shared.py,
  models/catalogue.py register_model); cache-init downloads a model by
  loading it through its handler
- model settings: extra_env on the catalogue item, applied to the
  process environment by set_model_config_env (shared/db_models.py);
  loaders read LOAD_IN_4BIT, USE_FAST, TRUST_REMOTE_CODE and
  LOW_CPU_MEM_USAGE with env_flag (models/standard_loader.py);
  handlers read others, such as NUM_STEPS and PRECISION
- worker: models/worker.py; ModelScheduler sweeps the queues and loads
  one model at a time in resident_model; a load failure publishes
  MODEL_LOAD_FAILED, drains the queue with errors and records
  failed_reason on the catalogue row; the API answers requests for a
  failed model with 409
- VRAM check: tools/power_sampler.py check_model_vram
- results cache: the API hashes a request body to a message id;
  shared/receiver_logic.py returns any stored status for that id
- lifecycle events: LifecyclePublisher (models/worker.py) publishes to
  LocalNotificationBackend (backend/messaging/local.py), which logs at
  DEBUG; the OpenAI routes (api/routes/openai.py) pass no backend at
  all; WorkerEvent (shared/db_models.py) is defined and unused, and
  backend/local/events.py is an unused copy of the backend
- usage: one UsageItem row per request (shared/usage_models.py), keyed
  by user
- API routes: api/routes/catalogue.py (GET /models,
  GET /models/{type}/{name}), api/routes/usage.py (a 501 stub);
  documented in docs/api.md

docs/architecture.md describes the platform as a whole.

## Findings

The first Grasmere run (2026-11-18), and the task that addresses each:

- the worker ran on the CPU: compose_files lacked "gpu", and "gpu"
  needs "cpu" before it (0002)
- Grasmere E4B is 15.9 GB in bf16 and does not fit across two 12 GB
  cards, so it needs 4-bit; the setting could only be made per model
  in the application's models.yaml (0003, 0004)
- a YAML boolean in extra_env crashed the whole worker, because
  settings were applied outside the load (0000)
- failure messages contained only the model name (0000)
- a failed model stayed failed: populate carried the mark over, and
  the results cache served the stored error for identical requests
  (0001)
- the catalogue logged its item count at INFO on every sweep, burying
  the worker log (0001)
- platform stop removed the applications network beneath a stopped
  executor, which then failed to start (0002)
- Open WebUI tried to reach Ollama on every page load (0002)
- load events went to a backend that discards them, so no model
  history exists, and the API logged a publisher warning on every
  request (0005)
- no single place shows a model's settings, status and history
  (0006, 0007)
- usage is recorded but cannot be read, and CPU offload is not
  recorded (0008)
- the data directories are undocumented, so resetting the database
  meant finding what to delete (0009)

Outside this workplan:

- a CPU request taking 502s ended in a 504 at the API's 300s wait,
  discarding the result (backlog: streaming chat completions)
- Open WebUI's tool definitions turned one greeting into 5163 input
  tokens (an operator setting in Open WebUI)

## Decisions

- the host overrides the application for model settings
- model settings are typed for the four loader keys, with extra keys
  allowed; a setting's name is its environment variable in lower case
- host model settings have three levels: global, type and name
- cache-init keeps downloading through the handlers and receives the
  host settings, with 4-bit off
- 4-bit on a worker with no CUDA device fails the load with a message
- events accumulate with no TTL
- the API is assumed authenticated; access is controlled at the
  infrastructure layer, so there are no admin routes
- cache populate clears a model's failure; there is no reset command

## Tasks

| Task | Change                                       | Depends on |
|------|----------------------------------------------|------------|
| 0000 | worker load failures                         | -          |
| 0001 | catalogue failures and the results cache     | -          |
| 0002 | platform stop, compose checks, verify        | -          |
| 0003 | model settings in models.yaml                | 0000       |
| 0004 | host model settings                          | 0003       |
| 0005 | stored lifecycle events                      | 0004       |
| 0006 | model detail from the API                    | 0005       |
| 0007 | marigold models inspect                      | 0006       |
| 0008 | model usage summary                          | 0007       |
| 0009 | data directories and reset                   | 0008       |
