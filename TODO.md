# TODO


## Workflow feature -- open items

### Compute steps: incomplete stubs

mask-diff and kmeans are NotImplementedError stubs in the executor
callable. Implement when a workflow example requires them.


### Known race: merge_workflow_state

Two parallel steps completing simultaneously produce two concurrent
executor Lambda invocations. Both call advance(), one finds no new
dispatchable steps and returns Pending(). Safe for dispatch, but both
attempt a load-modify-write on shared workflow state. A key written by
one may be overwritten by the other.

### Polling response: version and updated_at not implemented

The polling design (PRINCIPLES_polling.md) requires version and updated_at
alongside status. handle_status in polling/ecs.py returns status,
message_id, and result only. Temporal guard is unimplemented.

Implement before external users poll against the API.

### S3 reference pattern for large inputs

The 256 KB SQS limit blocks: tabular-classify, large audio (ASR), any
multi-document workflow step, and the evals product (hard prerequisite).

Users supply their own S3 bucket and key; the task role reads from it.
IAM design required before this can be fully specified.


# Model types and unclassified capabilities

Items here are acknowledged as future work but do not yet have handler
designs, implementation orders, or confirmed request/response shapes.
They are recorded so they are not lost between sessions.

When an item is ready to specify, move it to TODO_models.md with a handler
design. When it is ready to implement, add it to the relevant implementation
order list.

## Model types requiring investigation before specification

### Magika (Google) -- file type identification

pip-installed, no EFS cache entry. The model identifies file types from
raw bytes with a single forward pass.

Open question: how to reference a pip-installed model within the registry.
The handler pattern assumes weights on EFS; a pip-only model breaks that
assumption. Either the registry needs a pip-only model class, or Magika
is treated as a compute step (model_type: compute) in the executor.

Output shape: { label: str, score: float }
Request shape: bytes or S3 reference


### fasttext lid.176.bin -- language identification

pip-installed, no EFS cache entry. Same pip/no-cache consideration as
Magika. Identifies language of a text string, 176 languages, single
forward pass.

Output shape: { language_code: str, score: float }
Request shape: text string


### TabPFN (prior-labs) -- in-context tabular classification

Pre-trained transformer for tabular classification as in-context learning.
Training rows and test rows are both supplied in the request; the model
returns predicted labels with probabilities. No fine-tuning, no training
pipeline, no stored model artefact beyond the weights.

Intended use: scheduled batch task over large volumes of unlabelled rows
with a small fixed example set.

Open questions:
  - Upper bounds on training set size (designed for hundreds of rows)
  - Request size vs SQS limit; likely requires S3 reference for training
    and test data
  - Whether this fits the existing handler contract or needs a new pattern
    for multi-row request/response

Output shape: per-test-row { label: str, score: float }


### DETR (facebook/detr-resnet-50) -- object detection

Returns bounding boxes and class labels for objects in an image. The
output shape (list of {label, score, box: {xmin, ymin, xmax, ymax}}) does
not fit any current response type.

Requires a new output type for structured detection results, or a JSON
field alongside the image output. No implementation plan yet.


---

# Capability gaps with no current design

## LLM-generated workflow YAML from free text

An instruct model receives a plain-text description of a pipeline and
returns a validated workflow YAML. Failures during execution are fed back
to the model with a prompt to revise the definition. The UI is an
observation surface (current state, step outputs, failures) rather than
a workflow builder.

This changes the product interaction model significantly. No implementation
plan yet. The validator mentioned in TODO_workflow.md (Known limitations)
is a prerequisite.


### Rate limiting and user tiers

The usage table exists and records per-request metrics. Rate limiting
enforcement (per-hour, per-day limits; tier-based caps on concurrent ECS
tasks) has not been implemented.

When this becomes a priority, the implementation touches:
  - A rate_limits table (or a field on the users table)
  - The submission path from the API

Two distinct failure modes require two distinct controls:

  Volume abuse -- a key holder submits a high volume of unique request
  bodies to defeat cache deduplication, each triggering a task launch or
  queue entry. Controlled by a per-user submission rate limit (per-hour
  or per-day counter in DynamoDB, checked at submission time in
  handle_submission).

  Payload pathology -- valid or malformed payloads that crash the worker
  (OOM, unhandled exception). Controlled by monitoring per-account DLQ
  depth. When a single account's jobs account for more than a threshold
  of DLQ entries within a window, the account is throttled or placed on
  hold. A hard ban requires manual reinstatement; an automatic throttle
  with a reinstatement window (e.g. 24 hours) is self-healing and
  produces less friction for legitimate users who hit genuine bugs.

Policy decision required before implementation: hard ban vs. automatic
throttle-down with reinstatement window. This decision affects the data
model for account status.

Long instruct prompts (valid payloads, expensive by design) are a volume
abuse vector, not a payload pathology vector. They will never land in the
DLQ. The rate limit is the only control for this case.

### API test personas

Before opening access to external users, the submission and rate limiting
paths should be exercised with scripted personas covering the expected
range of usage patterns. Define personas now so that the threat model is
recorded alongside the controls designed to address it.

  honest_user      -- normal request volume, valid payloads, mixed model
                      types. Baseline for latency and result quality
                      checks.

  heavy_user       -- sustained high volume within expected rate limits.
                      Verifies that rate limit enforcement does not
                      interfere with legitimate high-volume use.

  cache_rider      -- repeated identical requests. Verifies cache
                      deduplication returns consistent results without
                      launching redundant tasks.

  prompt_spammer   -- high volume with unique request bodies to defeat
                      cache deduplication. Primary test for rate limit
                      enforcement at the submission path.

  prompt_stretcher -- valid instruct requests at maximum prompt length.
                      Tests visibility timeout heartbeat, inference
                      latency under load, and cost per request at the
                      upper bound.

  image_bomber     -- valid image-input requests with maximum-size
                      base64 payloads. Tests memory pressure on image
                      handler tasks and worker stability under large
                      inputs.

  dlq_trigger      -- crafted payloads designed to crash the worker
                      (e.g. corrupt image data, malformed JSON fields
                      that pass Pydantic validation but fail at inference
                      time). Verifies DLQ routing, circuit breakers, and
                      per-account DLQ monitoring (once implemented).

Prerequisite: rate limiting and DLQ monitoring must be implemented before
the spammer and dlq_trigger personas produce meaningful results. Run
honest_user and cache_rider first as smoke tests immediately after
deployment.


## Model catalogue leaderboard

Monitor the following sources on a regular cadence to identify models
worth adding to the catalogue:

  https://huggingface.co/spaces/lmsys/chatbot-arena-leaderboard
    Elo-ranked human preference data. Most reliable signal for instruct
    quality across general tasks.

  https://huggingface.co/spaces/open-llm-leaderboard/open_llm_leaderboard
    Open LLM Leaderboard v2. Automated benchmarks (MMLU-Pro, GPQA, etc).
    Weight towards reasoning and knowledge tasks.

  https://artificialanalysis.ai/leaderboards/models
    Includes throughput, latency, and price/performance. Useful for
    assessing whether a model is practical at Marigold's GPU tier costs.

Review cadence: monthly, or when a major model family releases.
New models go to TODO_models.md with GPU requirement and licence noted.

---

## Async-first inference -- shared jobs and webhook delivery

The queue-based architecture provides durability and decoupling that
synchronous HTTP inference cannot. Three features expose this to customers
explicitly.

### Webhook delivery

READY TO BUILD

Add an optional `callback_url` field to submission requests. When the worker
writes a completed result, a trigger fires a request to the callback URL.

This makes polling optional. Batch pipelines, CI/CD integrations, and
event-driven systems can receive results without maintaining a polling loop.

Implementation:
  - Add `callback_url: Optional[str]` to `MarigoldSQSMessage`.
  - Store `callback_url` in the DynamoDB results item alongside the result.
  - Add a DynamoDB Streams Lambda trigger on `results-cache` that fires on
    INSERT with `status=complete`.
  - The trigger Lambda reads `callback_url` from the item and POSTs the
    result payload. Retries three times with exponential backoff.
  - Only fire on `complete` and `error` status, not intermediate states.

### Result TTL control

READY TO BUILD

Allow submitters to specify result retention duration at submission time.
Currently TTL is hardcoded. A `ttl_seconds` field on the submission
controls how long the result is available for retrieval.

  - Default: 86400 (24 hours)
  - Maximum: 604800 (7 days)
  - Minimum: 300 (5 minutes)

Persistent results (ttl_seconds=0) are not supported

---

## Model selection aliases -- `best` and `fastest`

READY TO BUILD (prerequisite: warmth check via ECS API)

Two reserved values for `model` fields in API requests and workflow YAML
that abstract over specific model names and adapt to cluster state.

### `model: best`

Routes to the eval-recommended model for this task type and user account.
The recommendation is resolved from the DynamoDB recommendations table
keyed by `{user_id, model_type}`. If no recommendation exists for the
user, falls back to the platform default for that type.

Loads the model if it is not currently warm. Latency is secondary to
quality. Use in batch pipelines, overnight jobs, and quality-sensitive
workflows where the user is not waiting synchronously.

### `model: fastest`

Routes to the highest-quality currently warm model of the matching type
and GPU tier. Warmth is determined by a single ECS API call checking
which services have `runningCount > 0`.

Resolution order:
  1. If the eval-recommended model is warm, use it.
  2. Otherwise use the highest-ranked warm model of the same type and tier.
  3. If no warm model exists, fall back to `best` (load the recommendation).

Use in user-facing applications, interactive workflows, and any context
where the user is waiting synchronously for a response.

### Fallback behaviour

`fastest` never fails due to no warm models. It degrades to `best`
silently. The caller receives the best available model; the response
includes a `model` field in the result so the caller can see which
model was actually used.

### Implementation notes

Recommendations table lookup: existing table keyed by
`{user_id, model_type}`. If absent, use platform defaults defined in
a static config (not per-user, not per-eval -- just sensible defaults
by type, e.g. `qwen/qwen3-8b` for instruct on tier).

Both aliases work in:
  - Direct API requests: `POST /gen/instruct` with `"model": "fastest"`
  - Workflow YAML step inputs: `model_name: best`
  - The `/chat` endpoint (always uses `fastest` by default)

The `/chat` endpoint should default to `fastest` without requiring the
caller to specify it explicitly -- the chat use case is always
latency-sensitive.

---

## Wallet-based identity and decentralised authentication

READY TO BUILD (prerequisite: secp256k1 pubkey field on ModelRequest)

Replace email/password account creation with secp256k1 keypair authentication.
A user's identity is their Bitcoin or Ethereum address. The platform verifies
ownership via a signed challenge. No email provider, no OAuth, no passwords.

### Authentication flow

1. Client requests a challenge:
   GET /auth/challenge?address={bitcoin_or_ethereum_address}
   <- {challenge: "marigold:{timestamp}:{nonce}", expires: {unix_ts}}

2. Client signs the challenge with their wallet private key (off-platform).
   Any secp256k1-compatible wallet works: Bitcoin, Ethereum, hardware wallets.

3. Client submits the signature:
   POST /auth/verify
   {address, signature, challenge}
   <- {token: jwt, expires: 3600}

4. Platform verifies locally using ecrecover -- no blockchain contact required:
   recovered = ecrecover(challenge, signature)
   assert recovered == submitted_address
   Issue a short-lived JWT scoped to the address.

### What this enables

Identity without a centralised issuer
  The user's address exists independently of Marigold. Deleting a Marigold
  account does not invalidate the identity. Marigold going offline does not
  invalidate past signatures.

Cross-platform portability
  The same keypair authenticates across any platform accepting secp256k1
  signatures. No per-platform credentials.

Pseudonymity
  The address is public; the legal identity behind it is not. Customers
  with competitive sensitivity around their AI usage can operate without
  exposing organisational identity.

One key, three functions
  The secp256k1 keypair serves as: identity (address), authentication
  (challenge signature), and encryption (ECIES result encryption).
  A single wallet manages all three.

Public attestation
  A customer can publish a signed statement referencing a Marigold job ID.
  The signature is independently verifiable by any third party without
  contacting Marigold. Useful for regulated audit trails.

### Implementation notes

Challenge format: "marigold:{unix_timestamp}:{random_hex_16}"
Challenge TTL: 300 seconds. Replay prevention via conditional write
on the nonce -- mark used on first verify, reject on second.

JWT payload: {sub: address, iat, exp, scope: ["inference", "eval"]}
JWT signing: HMAC-SHA256 with a platform secret. Short expiry (1 hour),
refresh via re-signing a new challenge.

ecrecover: use the coincurve library (wraps libsecp256k1, same as Bitcoin Core).
No pure-Python fallback -- security-critical code must use the audited C library.

Ethereum addresses: lowercase hex with 0x prefix, EIP-55 checksum optional.
Bitcoin addresses: P2PKH (1...) or P2WPKH (bc1...) -- derive from compressed
public key via standard HASH160.

Both address formats derive from the same secp256k1 key. A user may register
either. The platform stores the raw compressed public key (33 bytes) and
derives the canonical address form for display.

### Not in scope

On-chain lookups: the platform never queries any blockchain. Verification
is purely local cryptography against the submitted address.

Token payments: out of scope for this feature. The keypair choice is
forward-compatible with Lightning Network payments but that is a separate
product decision.

ENS / DNS resolution: resolving human-readable names to addresses is a
useful UX improvement but not required for the core auth flow.

---

# Polling API

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

---

# Evals product

## Overview

The evals product runs models against labelled datasets and scores outputs
using the Marigold inference API. It is a batch tool, not a real-time
inference job.

All submission, polling, and result storage goes through the public API.
No direct backend access. This makes the eval pipeline a first-class
consumer of the platform -- the same interface a customer would use.

Market gap: existing eval tools (OpenAI Evals, PromptFoo, Braintrust) assume
text-in / text-out against an external API endpoint. None host models. None
support image generation eval, TTS eval, or cross-modal scoring. All of those
are first-class eval surfaces in Marigold because the models that run them
are already in the registry.

## Architecture

Evals are built on top of the pump tool infrastructure. The pump already
handles submission, history tracking, and result polling. Evals add a
dataset layer and a scoring layer on top.

```
tools/pump/
    __main__.py         -- CLI router (pump | audit | evaluate)
    pump.py             -- submit_job, dispatch, Job, ROUTE_MAP (shared)
    audit.py            -- poll results, report latency stats
    evaluate.py         -- load dataset, submit jobs, score results, report
    fixtures.py         -- synthetic sample inputs for pump load testing
    datasets/
        instruct.jsonl  -- labelled instruct eval dataset
        embedding.jsonl -- semantic similarity eval dataset
        tts.jsonl       -- TTS eval dataset
        text-eval.jsonl -- NER / PII detection eval dataset
```

The `evaluate` command reuses `pump.submit_job` and
`dashboard.history.write_entry` directly. The only additions are dataset
loading, result joining, and the scoring pass.

## Commands

```bash
# Submit eval jobs from a dataset (reuses pump submission path)
python3 -m tools.pump pump \
    --dataset tools/pump/datasets/instruct.jsonl \
    --once

# Fetch results and score against ground truth
python3 -m tools.pump evaluate \
    --dataset tools/pump/datasets/instruct.jsonl \
    --date 2026-05-17 \
    --metrics text-similarity llm-judge \
    --report

# Score without re-fetching (results already in history)
python3 -m tools.pump evaluate \
    --dataset tools/pump/datasets/instruct.jsonl \
    --date 2026-05-17 \
    --report
```

## Dataset format

JSONL, one record per eval case. Extends the pump history format with
`reference` and `metrics` fields.

```jsonl
{
  "id": "q001",
  "model_type": "instruct",
  "model_filter": null,
  "input": {
    "messages": [{"role": "user", "content": "Summarise the following..."}]
  },
  "reference": "Expected output text.",
  "metrics": ["text-similarity", "llm-judge"]
}
```

`model_filter` is null (run against all models of that type) or a list of
specific model names. This allows a single dataset to target a model family
comparison or a specific model.

The `id` field is used to join dataset records against history JSONL entries
at evaluation time. The pump sets the `nonce` from the dataset `id` so the
join is deterministic.

## Scoring modes

Standalone: no `reference` field. Each output is scored independently by
the declared metrics. Useful for safety, toxicity, and PII detection checks.

Reference comparison: `reference` field present. Semantic similarity between
output and reference is computed. Useful for summarisation, translation, and
factual recall evaluation.

LLM-as-judge: `llm-judge` in metrics list. A configurable judge model
(default: qwen/qwen3-8b) receives the input, reference, and output and
returns a score 1-5. The judge prompt and model are configurable per dataset.
All judge calls go through the API -- no direct model access.


## Evaluate subcommand flow

```
evaluate.py:

1. Load dataset JSONL -- get {id, input, reference, metrics}
2. Read history JSONL for the date -- get {message_id, nonce, model, submitted_at}
3. Join on nonce == id -- match eval cases to submitted jobs
4. Fetch results from API -- get {output, duration_ms, usage}
5. For each result:
   a. If reference present: submit text-similarity job to API
   b. For each metric: submit scoring job to API
      (text-eval, llm-judge, etc -- all through /eval/* endpoints)
6. Poll scoring results
7. Write evaluation report:
   - per-model p50/p95 latency
   - per-metric score distribution
   - per-case result table (id, model, output[:80], scores)
```

Steps 5-6 are themselves pump submissions -- the scoring models run in the
same ECS workers as inference models. No special infrastructure needed.


## Default metric suites by output type

instruct:       text-similarity (with reference)
                llm-judge (with reference)
                openai/privacy-filter (standalone -- check for PII leakage)

text-embedding: text-similarity against reference embedding
                (measures retrieval quality on labelled pairs)

tts:            BLOCKED: ASR handler required to transcribe back to text,
                then text-similarity against source. No equivalent exists
                in any competing eval tool. High priority once ASR is
                available.

text-eval:      f1-score against reference entity spans (NER)
                precision/recall against reference PII labels


## Eval-specific surfaces (future)

text-to-image:  submit prompt dataset, generate images, score each for
                safety (nsfw-image-detection), aesthetic quality
                (cafe-aesthetic), and CLIP alignment against the prompt

captioning:     submit image dataset with reference captions, run img2txt,
                score output against reference using text-similarity

VQA:            submit image + question pairs, run img2txt, score answer
                against reference

cross-modal:    submit image + text pairs, score alignment using
                clip-ViT-B-32; covers image/caption, image/prompt,
                product photo/description pairs


## Metric catalogue

All scoring uses existing registry models via the API.

  text-similarity:  intfloat/multilingual-e5-large-instruct
                    or sentence-transformers/all-minilm-l6-v2

  text-eval:        openai/privacy-filter (PII)
                    dslim/bert-base-ner (NER)
                    dslim/bert-large-ner (NER, higher quality)

  llm-judge:        qwen/qwen3-8b (default, configurable per dataset)

  image:            falconsai/nsfw_image_detection
                    cafeai/cafe_aesthetic

  cross-modal:      openai/clip-vit-large-patch14


## Result format

JSONL output, one record per eval case:

```jsonl
{
  "id": "q001",
  "model": "qwen/qwen3-8b",
  "submitted_at": "2026-05-17T10:00:00Z",
  "duration_ms": 17233,
  "input": "...",
  "output": "...",
  "reference": "...",
  "scores": {
    "text-similarity": 0.87,
    "llm-judge": 4,
    "openai/privacy-filter": []
  }
}
```

Also written as a CSV summary for human review and content publishing.


## Public leaderboard

Once eval datasets are stable, results can be published as a public
leaderboard at marigold.run/models or a dedicated /evals page. This
creates SEO content that updates automatically as new models are added
and eval runs complete.

The leaderboard answers: "which model performs best on UK compliance
document summarisation?" -- a query no existing benchmark addresses.

For the self-hosted system, allow submission of benchmarks and evals
with attribution to the submitting user.


## Implementation order

1. `fixtures.py` -- move synthetic pump inputs out of pump.py (immediate)
2. `--dataset` flag on pump subcommand -- load inputs from JSONL instead
   of fixtures (required for evaluate)
3. `evaluate.py` -- dataset loading, result joining, scoring submission,
   report (core eval pipeline)
4. `datasets/instruct.jsonl` -- first labelled dataset, instruct models,
   10-20 cases with reference outputs
5. Per-type p50/p95 in audit report -- already done, feeds into evaluate
   report structure
6. LLM-as-judge scoring -- judge prompt template, configurable model
7. TTS eval surface -- after ASR handler is available
8. Public leaderboard -- after 2-3 eval datasets are stable

## Dependencies

BLOCKED (TTS eval only): ASR handler for transcription scoring
NOT BLOCKED: all other eval surfaces work with current infrastructure

The previous S3 reference pattern and workflow fan-out dependencies are
removed -- the pump-based architecture submits jobs directly through the
API without requiring workflow infrastructure.

## Leaderboard references

https://huggingface.co/spaces/lmsys/chatbot-arena-leaderboard
https://huggingface.co/spaces/gorilla-llm/berkeley-function-calling-leaderboard
https://artificialanalysis.ai/leaderboards/models
https://huggingface.co/datasets?benchmark=benchmark:official&sort=trending

---

# Torrent distribution: bootstrap seed + opportunistic client seeding (open)

Architecture (squashfs build, make-torrent, DHT, separate marigold-cache
package) is settled from prior discussion.

Decided: client-side seeding via opt-in flag, using python-libtorrent
(already the planned dependency). Running marigold/model_cli instances
seed completed .sqfs files back into the swarm when enabled.

Open:
  - opt-in UX: config flag, default false, one-line explanation at first run
  - bootstrap seed hosting: Hetzner Dedicated (AX line) over Cloud, for
    unmetered/high-allowance bandwidth suited to sustained upload --
    confirm current AUP on P2P traffic before committing
  - NAT/inbound reachability expectations for client peers behind
    unconfigured home routers
  - whether bootstrap seed needs more than one box/region, now lower
    priority since it is not the sole distribution path
