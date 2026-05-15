# Polling API Design

## The Problem With Simple Polling

Most polling implementations are fragile because they treat status as a
boolean: done or not done. This breaks in two common scenarios:

1. A cached "complete" status from a previous operation terminates polling
   before the new operation finishes.
2. A non-trivial client (CLI, mobile, non-React web) has no framework cache
   to invalidate and must implement its own temporal reasoning, usually
   badly.

## The Pattern

Design polling endpoints so that any client can implement correct polling
using only server-provided values, with no reliance on client-side
framework machinery.

### Two signals, not one

Expose two independent signals from the same underlying resource:

- **Version** - detects that the resource has changed (an etag or hash)
- **Status** - describes the current state of the operation

Neither alone is sufficient. Version without status requires the client to
fetch the full resource to determine completion. Status without version
gives no change detection signal and is vulnerable to stale cache reads.

### Both signals must carry a timestamp

Without a timestamp, a client cannot determine whether a signal predates
or postdates its own submission. This is the most commonly missed detail.
```json
{
    "version": "0x8DE866B1F2A3C4D",
    "status": "complete",
    "updated_at": "2026-03-20T10:44:18+00:00"
}
```

`updated_at` should come from the storage layer (blob last_modified, DB
row updated_at), not from application code. Application-generated
timestamps are vulnerable to clock skew and write failures.

### Collapse to one endpoint

If version and status describe the same resource, serve them from one
endpoint. Two poll targets at different frequencies is a client-side
workaround for a missing server-side capability.
```
GET /resource/{id}/status
```

returns version, status, and updated_at in a single cheap response with
no body download.

## The Temporal Guard

The key correctness property: a client must reject any status signal whose
`updated_at` predates the client's submission time.
```python
submitted_at = now()
last_version = None

while True:
    r = get(f"/resource/{id}/status")
    updated_at = parse_iso(r["updated_at"])

    if updated_at > submitted_at:
        if r["version"] != last_version:
            last_version = r["version"]
            fetch_and_display()

        if r["status"] == "complete":
            break

    sleep(poll_interval)
```

This loop is correct regardless of client framework. The temporal guard
replaces React Query's query key cache, Redux middleware, or any other
framework-specific cache invalidation mechanism.

## Designing Status Values

Status values should reflect the actual processing pipeline, not just
done/not-done. This gives clients and operators visibility into where a
long-running operation is, and makes debugging easier.
```
created -> pending -> complete
                   -> failed
```

Rules:
- Status values are lowercase strings, not integers or booleans
- Terminal states are `complete` and `failed`
- Intermediate states should reflect real pipeline stages, not be
  invented for the sake of granularity
- A `failed` status should be accompanied by an error field
```json
{
    "version": "0x8DE866B1F2A3C4D",
    "status": "failed",
    "updated_at": "2026-03-20T10:44:18+00:00",
    "error": "upstream service unavailable"
}
```

## Poll Frequency

Poll the status endpoint at a single fixed interval. Variable frequency
polling (fast for version, slow for status) is a symptom of having two
endpoints where one would do.

A reasonable default is 2 seconds for human-facing operations. Sub-second
polling rarely improves perceived responsiveness and increases server load
linearly.

## Circuit Breaker

Any polling loop must have an exit condition beyond normal completion.
```python
MAX_ERRORS = 5
MAX_WAIT = 300  # seconds

errors = 0
deadline = now() + MAX_WAIT

while now() < deadline:
    try:
        r = get(f"/resource/{id}/status")
        errors = 0
        # ... normal logic
    except Exception:
        errors += 1
        if errors >= MAX_ERRORS:
            raise PollFailure("too many consecutive errors")
    sleep(poll_interval)
else:
    raise PollTimeout(f"operation did not complete within {MAX_WAIT}s")
```

Without this, a network partition or server error leaves the client
polling indefinitely.

## What Not To Do

**Do not add a `completed_at` field separate from `updated_at`.** The
final write's `updated_at` is already the completion timestamp. A
separate field creates two sources of truth that can diverge if a write
fails partway through.

**Do not derive `updated_at` in application code.** Use the timestamp
from the storage layer. Application-generated timestamps are not
guaranteed to be consistent with what was actually written.

**Do not poll the full resource for change detection.** A status endpoint
should be cheap - properties and metadata only, no body download. If a
client needs the full resource it fetches it once after the status
endpoint signals completion.

**Do not use HTTP caching headers as a substitute for version.** Cache
headers are infrastructure concerns. Version is a business concern. They
serve different purposes and should not be conflated.
