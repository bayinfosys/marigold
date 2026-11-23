# Breakdown

1. Add a "Code layers" section to architecture.md with the table, the
   rule, and the command that checks it.
2. Write scripts/layer_check.py: read the table from architecture.md,
   build the import graph of package/src with ast, and report cycles
   between components and imports against the layers, each with the
   importing file; exit 1 when it reports anything.
3. Run it, and confirm it reports nothing.
4. Add the check to the steps for each task in tasks/README.md.
