# Breakdown

1. Add [models] to the host config: settings at the top level, with
   `types` and `names` tables of the same settings.
2. Carry the section into the worker and API containers as JSON in
   MARIGOLD_MODEL_SETTINGS, empty by default.
3. Write the resolution: for each setting, its value and its source,
   in the order loader default, application, host, host type, host
   name.
4. Resolve at load in the worker and log the result as one line.
5. Regenerate configuration.md, describing the resolution order and
   the settings each handler reads.
