# marigold models inspect

`marigold models inspect` lists the catalogue: each model's name,
type, application and status. With a model name it prints the model's
settings and their sources, its status and failure reason, its last
load and its recent events. Everything comes from the API.

Effects:

- the first command to run when a model fails
- the command takes the same shape as `marigold cache inspect`, which
  gives a model's files on disk
- it works against any platform the configured API address reaches
- getting-started.md and the README describe it
