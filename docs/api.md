---
title: API
description: Submitting and polling jobs, binary outputs, the catalogue with each model's settings, events and usage, and the OpenAI-compatible endpoints of the Marigold API.
nav_order: 11
---

# API

The platform API answers at `http://localhost:8000` on the host, and at
`MARIGOLD_API_BASE` inside an instance. The interactive schema is at
`/docs`.

## Submitting and polling

Every submission route -- `/embed/...`, `/eval/...` and `/gen/...`, one
per [model type](model-types.md) -- takes a JSON body with `model` and
the type's fields, and returns a `message_id` with a `Location` header
naming the poll route. Polling `GET /output/{mode}/{task}/{message_id}`
returns 202 until the job is terminal, then 200 with `status` of
`complete` or `error`.

Two fields on every request matter to applications:

- `application_id` -- set it from `MARIGOLD_APPLICATION_ID`. It is
  recorded against usage, and it is part of the request hash, so
  identical requests from different applications are distinct jobs.
- `nonce` -- identical bodies return a cached result. A fresh nonce
  forces a new sample, which a smoke test or an agent sampling a
  distribution needs.

`platform-model-test` in the [examples](examples.md) registry is the
reference client: it lists the catalogue, submits one request per
model, polls, and exits 0 only if every tested model completed.

## Binary outputs

A completed job with binary outputs returns references under
`outputs`, each with `path`, `mimetype`, `bytes` and `sha256`. The
bytes come from `GET /output/{mode}/{task}/{message_id}/{field}`; the
reference's `sha256` checks what arrived. Where they are stored is set
in [Configuration](configuration.md).

## Catalogue

| Route | Returns |
|---|---|
| `GET /models` | every model in the catalogue |
| `GET /models/{model_type}/{model_name}` | one model, with its settings, recent events and usage |

A model appears in the catalogue once `marigold cache populate` has
downloaded it.

### One model

`GET /models/{model_type}/{model_name}` returns the catalogue entry,
with `failed_reason` set while the model is marked failed, and three
fields that describe what applies to the model, what has happened to
it and what it costs to run:

- `settings` -- every setting a load of the model resolves, each with
  its value and the level it came from: `default`, `application`,
  `host`, `host type` or `host name` (see
  [Configuration](configuration.md#model-settings)). It holds the
  application's settings resolved against the host's.
- `events` -- the model's 50 most recent lifecycle events, newest
  first, each with `timestamp`, `event_type`, `message_id` and
  `payload`. The events and their payloads are listed in
  [Architecture](architecture.md#lifecycle-events).
- `usage` -- a summary of every usage row recorded for the model, from
  every user and application:

  | Field | Meaning |
  |---|---|
  | `requests` | requests recorded; the only field when there are none |
  | `input_tokens`, `output_tokens` | totals |
  | `duration_ms` | `p50`, `p90` and `p99` of each request's total duration |
  | `load_time_ms_mean` | mean model load time |
  | `vram_bytes_peak` | the highest peak VRAM of any request |
  | `power_watts_mean`, `power_watts_peak` | mean of each request's mean GPU power draw; the highest peak |

  Usage rows are keyed by user, so the summary reads the whole usage
  table, which suits the usage of one host.

```json
{
  "name": "qwen/qwen3-8b",
  "type": "instruct",
  "failed_reason": null,
  "settings": {
    "load_in_4bit": {"value": true, "source": "host"},
    "low_cpu_mem_usage": {"value": true, "source": "default"},
    "trust_remote_code": {"value": false, "source": "default"},
    "use_fast": {"value": false, "source": "default"}
  },
  "events": [
    {
      "timestamp": "2026-11-19T21:04:11.524000+00:00",
      "event_type": "MODEL_LOADED",
      "message_id": null,
      "payload": {"footprint_bytes": 5926000000, "dtype": "torch.bfloat16", "placement": {"cuda:0": 3100000000, "cuda:1": 2826000000}}
    }
  ],
  "usage": {
    "requests": 214,
    "input_tokens": 182330,
    "output_tokens": 61207,
    "duration_ms": {"p50": 2310, "p90": 6120, "p99": 11840},
    "load_time_ms_mean": 21430.0,
    "vram_bytes_peak": 7120000000,
    "power_watts_mean": 141.2,
    "power_watts_peak": 228.5
  }
}
```

The example shows a subset of the entry's fields.

## OpenAI-compatible endpoints

`GET /v1/models`, `POST /v1/chat/completions` and `POST /v1/embeddings`
wrap the submit and poll path for unmodified OpenAI SDK clients
(Open WebUI, LangChain, LangGraph, Continue and others).

- `stream=true` returns correctly framed SSE chunks, without
  token-level streaming.
- Tool calls carry ids in both directions, so several calls in one
  turn round-trip. `tool_choice` accepts `auto` and `none`.
- `response_format` (`json_object`, `json_schema`) is checked after
  generation; a reply that does not match fails the request with 422
  (`output_invalid`).
- `chat_template_kwargs` passes through to the model's chat template,
  for example `{"enable_thinking": false}` for Qwen3.
- `X-Marigold-Application-Id` attributes a request to an application.

`tool-call-conformance` in the examples registry checks all of this
against the instruct models in a catalogue.
