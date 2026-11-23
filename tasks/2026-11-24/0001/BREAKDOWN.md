# Breakdown

1. Docstrings and comments under package/src/marigold/: each module
   named by its top-level path, such as `shared.registry` or
   `models.entrypoint_handlers`, gains the `marigold.` prefix. File
   names such as models.yaml and models.md stay.
2. README.md: the layout section shows package/src/marigold/.
3. docs/: each path under package/src becomes package/src/marigold/,
   in model-types.md, publishing.md, architecture.md and any other
   document that names one; each module named by its top-level path
   gains the prefix.
4. docs/architecture.md, Code layers: the components keep their short
   names, and the text says each is a subpackage of marigold.
