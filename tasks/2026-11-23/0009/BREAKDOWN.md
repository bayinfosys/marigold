# Breakdown

1. Move models/catalogue.py to shared/catalogue.py.
2. Change every import: models/worker.py, shared/receiver_logic.py, the
   routes under api/routes/, the CLI and tools/cache_cli.py.
3. Change any document that names models/catalogue.py.
