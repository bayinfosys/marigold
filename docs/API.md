---
title: API
description: Submitting and polling jobs, binary outputs, the catalogue and the OpenAI-compatible endpoints of the Marigold API.
nav_order: 10
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

## Catalogue and usage

| Route | Returns |
|---|---|
| `GET /models` | every model in the catalogue |
| `GET /models/{model_type}/{model_name}` | one model |
| `GET /usage/{key}/{period}` | usage recorded against a key |

A model appears in the catalogue once `marigold cache populate` has
downloaded it.

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
