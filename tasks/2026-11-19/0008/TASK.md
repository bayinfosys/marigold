# Model usage summary

The model detail response and `marigold models inspect` include a
summary of all usage recorded for the model: requests, tokens in and
out, duration percentiles, mean load time, peak VRAM, and mean and
peak power. The worker records CPU offload bytes again. The
unimplemented /usage route is removed.

Effects:

- an operator sees what a model costs to run from the command that
  shows its configuration and history
- the summary reads every usage row for the model, since rows are
  keyed by user; this suits a single host
- the API drops a route that only returned 501
- docs/api.md describes the summary and drops the route
