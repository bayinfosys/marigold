# Worker utilities in models/

power_sampler.py and environment.py move from tools/ to models/, and
every import of them changes.

Effects:

- the worker no longer imports from tools/, which removes the cycle
  between models and tools
- tools/ holds the entry points: cache-init and the CLI tools
- no behaviour changes

Depends on 0006.
