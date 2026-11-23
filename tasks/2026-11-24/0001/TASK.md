# Module names under marigold in the text

Docstrings, comments, README.md and docs/ name each module by its path
under `marigold`, and each source path under package/src/marigold/.

Effects:

- a module named in the text, such as marigold.shared.registry, is the
  one Python imports
- a path given in the documentation exists in the tree
- no code changes

Depends on 0000.
