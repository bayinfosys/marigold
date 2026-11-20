# Breakdown

1. Add a "Data directories" section to architecture.md: data/postgres,
   data/models, data/applications and data/webui, each with its
   contents and the effect of deleting it.
2. Document the reset: platform stop, remove data/postgres, platform
   start, cache populate.
3. Add verify across installs, host model settings and models inspect
   to the README feature list.
