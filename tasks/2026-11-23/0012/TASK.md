# Declared layers and a check

architecture.md declares the code layers in a table, and
scripts/layer_check.py reads that table, reports each cycle between
components and each import against the layers, and exits 1 when it
finds any.

| Layer | Components |
|---|---|
| 3 entry points | cli, tools |
| 2 services | api, models |
| 1 adapters | backend |
| 0 core | shared |

A component imports only from layers below its own, and components in
one layer import none of each other.

Effects:

- the layering is written down once, in architecture.md, and checked
  against the code
- every patch from this one on runs the check, which reports nothing
- tasks/README.md lists the check among the steps for each task

Depends on 0008, 0009, 0010 and 0011.
