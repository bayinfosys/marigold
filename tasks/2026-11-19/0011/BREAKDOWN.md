# Breakdown

1. Add a "Data directories" section to architecture.md: data/postgres,
   data/models, data/applications and data/webui, with contents and
   the effect of deleting each.
2. Document the reset: platform stop, remove data/postgres, platform
   start, cache populate.
3. Add verify across installs, host model settings and models inspect
   to the README feature list.
