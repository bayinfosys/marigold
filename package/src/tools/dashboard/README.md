# Marigold Dashboard

Terminal dashboard and load pump for Marigold private inference infrastructure.

Requires only an API key and AWS credentials -- no access to the internal
repo or generated config files.

## Structure

```
tools/
    pump.py                  -- load pump (replaces aws_pump_usage.py)
    dashboard/
        config.py            -- env vars, boto3 client singletons
        fetch_api.py         -- Marigold API calls (GET /models.json)
        fetch_aws.py         -- AWS boto3 calls (ASG, ECS, SQS, CW, DDB)
        transform.py         -- dataclasses, aggregation, partition_models
        history.py           -- pump job history (read/write JSONL)
        render/
            console.py       -- terminal output, ANSI colour
        __main__.py          -- entry point
```

## Usage

```bash
# Dashboard -- one shot
python3 -m tools.dashboard --once

# Dashboard -- continuous, 30s refresh
python3 -m tools.dashboard --interval 30

# Load pump -- one round
python3 -m tools.pump --once

# Load pump -- continuous, all model types
python3 -m tools.pump --interval 60

# Load pump -- specific types only
python3 -m tools.pump --once --types instruct,text-embedding
```

## Environment

| Variable | Default | Description |
|---|---|---|
| MARIGOLD_API_BASE | https://api.dev.mdl.bayis.co.uk | API endpoint |
| MARIGOLD_API_KEY | | API key (required) |
| MARIGOLD_ECS_CLUSTER | bayis-vecmdl-dev-inference | ECS cluster name |
| MARIGOLD_PROJECT | vecmdl | Project tag for ASG filter |
| MARIGOLD_PREFIX | bayis-vecmdl-dev | Resource name prefix |
| MARIGOLD_ORG | bayis | Organisation prefix |
| MARIGOLD_PUMP_HISTORY | ~/.marigold | Pump history directory |
| MARIGOLD_DYNAMODB_TABLES | (comma-separated list) | Tables to monitor |
| MARIGOLD_LOG_GROUP_PREFIX | /bayis/vecmdl/dev | CloudWatch prefix |
| AWS_REGION | eu-west-2 | AWS region |

## Dashboard output

The dashboard renders three sections:

**Infrastructure** -- one row per EC2 instance, grouped by ASG. Each running
model is shown as a sub-row under its instance with ECS service counts and
SQS queue depth inline.

**Backlog** -- models with queued messages but no running task. These are
waiting for a worker to start.

**Unused** -- models with no queued messages and no running task. Listed
compactly.

Followed by DynamoDB write metrics and a recent error count from CloudWatch.

## Pump history

Every job submitted by the pump is recorded to a JSONL file in
`MARIGOLD_PUMP_HISTORY`. One file per calendar day: `YYYY-MM-DD.jsonl`.

Each record contains `message_id`, `model`, `model_type`, `mode`, `task`,
`submitted_at`, `nonce`, and `poll_url`. The `poll_url` field contains the
correct poll path for that job type, so results can be queried later without
reconstructing the routing convention.

```python
from tools.dashboard.history import write_entry, read_entries

# Write (called automatically by tools/pump.py)
write_entry(message_id, model_name, model_type, nonce=nonce)

# Read last 2 days
entries = read_entries(days=2)
```

## Data sources

The dashboard combines two independent data sources:

- **Marigold API** (`GET /models.json`) -- model catalogue, hash-to-name
  mapping. Requires `MARIGOLD_API_KEY`.
- **AWS boto3** -- ASG state, ECS container instances and services, SQS
  queue depths, DynamoDB metrics, CloudWatch logs. Requires AWS credentials.

Neither source depends on the other. If the API is unreachable the
infrastructure section still renders; if AWS credentials are missing the
model catalogue renders without placement data.
