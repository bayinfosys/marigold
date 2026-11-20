# marigold models inspect

`marigold models inspect` lists the catalogue. With a model name it
prints the model's settings and their sources, its status and failure
reason, its cache entry, its last load and its recent events, read
from the API.

Effects:

- the first command to run when a model fails
- the command takes the same shape as `marigold cache inspect`
- it works against any platform the configured API address reaches
