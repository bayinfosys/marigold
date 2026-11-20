# Catalogue failures and the results cache

Populating an application writes each model's catalogue row afresh
from models.yaml, which clears a recorded failure. The API stops
serving stored errors from the results cache, so a request repeated
after a failure reaches the worker. The catalogue's per-sweep item
count moves to DEBUG.

Effects:

- `marigold cache populate <application>` retries a failed model
- a model fixed after a failure receives the requests that failed
- the worker log at INFO shows scheduling, loads and requests
- architecture.md describes how a failure is recorded and cleared
