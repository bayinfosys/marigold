# Dashboard TODO

## Storage backends

The dashboard currently renders point-in-time snapshots with no persistence.
Adding a storage backend would enable trend views, alerting, and historical
queries.

- [ ] DynamoDB backend -- write each DashboardData snapshot to a DynamoDB
      table keyed by timestamp. Enables the public metrics endpoint to read
      rolling averages without running the dashboard continuously.

- [ ] PostgreSQL backend -- full time-series storage for infrastructure and
      model metrics. Enables complex queries (latency percentiles over time,
      queue depth trends, per-model pass rate regression). Requires standing
      up an RDS instance; deferred until usage warrants it.

- [ ] S3 backend -- write snapshots as JSON to S3 with a prefix of
      `dashboard/{YYYY-MM-DD}/{HH-MM-SS}.json`. Simple, cheap, no new
      infrastructure. Readable by Athena for ad-hoc queries. Good interim
      option before Postgres.

## Output renderers

The render layer is decoupled from transform. Adding a renderer requires
implementing a function with signature `render(data: DashboardData) -> None`
and registering it in `__main__.py`.

- [ ] HTML renderer -- static HTML page with a table per section. Write to
      S3 on each refresh cycle. Serve via CloudFront as a lightweight
      internal status page. No JavaScript required for basic output.

- [ ] JSON renderer -- already stubbed in `__main__.py`. Extend to write
      the full DashboardData as structured JSON rather than the current
      summary-only output. Useful for piping to other tools or ingesting
      into the S3 backend.

- [ ] Terminal watch mode -- clear screen and re-render in place rather than
      appending. Use `curses` or simple ANSI clear sequences. Makes
      continuous mode (`--interval 30`) usable as a live display.

## Public metrics endpoint

The eval pump produces `summary.json` per model. The dashboard collects
infrastructure and queue stats. Together they have everything needed for
a public read-only metrics endpoint.

- [ ] Aggregation Lambda -- hourly job reads all model `summary.json` files
      from S3 and writes a combined `metrics.json`. The Lambda is triggered
      by EventBridge on a schedule.

- [ ] `GET /metrics/models` endpoint -- serves `metrics.json` from S3 via
      API Gateway S3 integration. No auth required. Returns per-model
      pass rate, latency percentiles, and availability status.

- [ ] Per-model pages on marigold.run -- Jekyll templates fed by the public
      endpoint. One page per model showing latency trend, pass rate history,
      and capability summary. SEO surface for "best open-weight model for X"
      queries.

## Job audit tool

The pump history records `message_id` and `poll_url` for every submitted job.
A job audit tool would query DynamoDB for the final state of those jobs and
report pass rates, latency, and usage statistics.

- [ ] `tools/job_audit.py` -- reads history entries, queries
      `results-cache` DynamoDB table by message_id, computes per-model
      completion rate and latency. Replaces manual log trawling for
      understanding pump round outcomes.

## Model placement awareness

The dashboard currently shows which model is on which instance but does not
surface placement quality.

- [ ] Warn when a model is placed on the wrong capacity tier -- e.g. a gpu-sm
      model landing on a CPU instance due to capacity provider misconfiguration.

- [ ] Show EFS cache warm status per model -- a cold model (not yet loaded
      from EFS) has a longer first-response latency. The dashboard could flag
      models where the last successful load took more than 2x the rolling
      median, indicating EFS cache pressure or a cache miss.

## DynamoDB launch guard integration

Currently the dashboard's `is_active` check uses ECS `list_tasks` which has
an eventual consistency window. A DynamoDB conditional write guard would
eliminate duplicate task launches during model load.

- [ ] `running_models` DynamoDB table -- worker writes a row on startup
      with `attribute_not_exists` condition, deletes on exit. Lambda checks
      this table instead of calling ECS. Dashboard reads from the same table
      for placement data, replacing the `fetch_running_tasks` + task
      description calls with a single DynamoDB scan.

## Wallet-based identity for pump history

The pump history currently uses a random nonce per round. Once wallet-based
identity is implemented on the platform, the pump can sign each submission
with a secp256k1 private key. The `message_id` + signature pair provides
cryptographic proof of submission origin, enabling per-customer audit trails
that neither Marigold nor the customer can forge.

- [ ] Add optional `MARIGOLD_SIGNING_KEY` env var to the pump. If set,
      sign each submission payload before sending and record the signature
      in the history entry.
