# TODO.md

TODO.md at the repository root lists the work no workplan addresses,
each item with where it was found:

- the worker creates four tables of its own at startup (architecture.md,
  Access model)
- assigning models to specific workers (architecture.md, Scaling)
- the package rename to marigold/{core,cli,api}, with the library split
  from the CLI
- separate application, execution and run identifiers, as pydantic
  types, so a run traces to the execution and application it belongs to
- `marigold models inspect` finds the last load only within the 50 most
  recent events

Effects:

- architecture.md's two references to TODO.md resolve
- future work is recorded in the repository, where a workplan can take
  items from it
