# Breakdown

1. Pass MARIGOLD_MODEL_SETTINGS to the API service, empty by default.
2. Read a model's recent events from the table, newest first, with a
   fixed limit.
3. Resolve the model's settings in the API from the catalogue entry
   and MARIGOLD_MODEL_SETTINGS.
4. Add `settings` and `events` to the detail response.
5. Describe the response in docs/api.md.
