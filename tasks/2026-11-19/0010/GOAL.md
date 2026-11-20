# Model usage summary

The model detail response and `marigold models inspect` include a
usage summary for the model over a period: requests, tokens in and
out, duration percentiles, mean load time, peak VRAM, and mean and
peak power. The worker records CPU offload bytes again. The
unimplemented /usage route is removed.

Effects:

- an operator sees what a model costs to run from the same command
  that shows its configuration and history
- the API drops a route that only returned 501
