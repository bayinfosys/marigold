# Model settings in models.yaml

A model entry in models.yaml declares loader settings under
`settings:`, typed for the four loader keys and open to the further
keys individual handlers read. A setting's name is its environment
variable in lower case. `settings:` replaces `extra_env`.

Effects:

- YAML booleans and numbers validate as settings
- models.yaml files using extra_env lose those settings until they
  move to `settings:`
- existing installs re-run `marigold cache populate <application>` to
  rewrite their catalogue rows
- handler docstrings, the API field description and applications.md
  use one vocabulary
- the host settings in 0004 share the same type
