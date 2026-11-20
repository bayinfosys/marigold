# Breakdown

1. Add [models] to HostConfig: ModelSettings at the top level, with
   `types` and `names` tables of ModelSettings.
2. Write [models] as JSON to MARIGOLD_MODEL_SETTINGS in compose_env(),
   and pass it, empty by default, to the worker and cache-init
   services.
3. Write the resolution beside ModelSettings: for each setting, its
   value and its source, in the order loader default, application,
   host, host type, host name.
4. Read MARIGOLD_MODEL_SETTINGS once at worker start; resolve at each
   load, apply the result, and log it as one line with sources.
5. Resolve the same way in cache-init, with load_in_4bit off.
6. In the loader, fail when load_in_4bit is set and no CUDA device is
   present, with a message saying 4-bit needs a GPU.
7. Regenerate configuration.md and describe the resolution order and
   the settings each handler reads.
