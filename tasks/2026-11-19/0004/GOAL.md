# Host model settings

The host config gains a [models] section that sets model loader
settings globally, by model type and by model name. At each load the
worker resolves a model's settings from the loader defaults, the
application's models.yaml and the three host levels, in that order,
and logs every value with its source. The host takes precedence over
the application.

Effects:

- an operator loads Grasmere in 4-bit on 12 GB cards with
  `[models] load_in_4bit = true`, leaving the application unchanged
- hardware-dependent settings such as quantisation belong to the
  host; the host can refuse trust_remote_code for every application
- a standalone compose run carries no host settings
- configuration.md documents the section and the resolution order
