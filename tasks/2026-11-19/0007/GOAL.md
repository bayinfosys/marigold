# Stored lifecycle events

Every lifecycle event published by the worker and the API is stored as
a row, keyed by model and ordered by time. Load events carry the
resolved settings with their sources, the footprint, the dtype, the
placement on each device and any error.

Effects:

- a model's load history survives restarts and log rotation
- the API stops logging lifecycle publisher warnings
- model detail (0008) and models inspect (0009) read from these rows
- rows accumulate with no TTL
