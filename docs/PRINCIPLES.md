# Marigold -- Principles

These principles record the reasoning behind recurring design decisions.
They guide new work and explain why the system is built the way it is.
Each ends with what it implies for the design.

---

## 1. The fat protocol

Marigold is an expression of the Fat Protocol Thesis applied to neural
networks. Model weights are the fat layer: learned, generalised and
opaque. Typed operations -- a capability class, a model and an input
set -- are the protocol primitives. Each operation produces an immutable
result drawn from the distribution the model defines over its inputs.

Applications are thin clients over that surface. They declare what they
need, reference the results, and hold no weights of their own. Because
results are samples from model distributions, they are
non-deterministic, and applications are designed to be robust to that.

Implication: an application is code and a list of required models.
Everything heavy lives in the shared cache, behind the protocol.

---

## 2. All computation is model inference

No custom classifiers, no regex-based routing, no hard-coded rule sets
or keyword lists. Every branch condition, classification, quality gate
and scoring decision is the output of a model trained on data. Custom
code handles data flow -- routing, mapping, persistence, retrieval,
external calls -- and makes no decisions.

A similarity search returning candidates is retrieval. A step that
turns a similarity score into a branch on its own, without an
eval-backed model step between, is a decision wearing a retrieval
step's clothing, and does not belong at the tool layer.

Implication: every decision is inspectable, reproducible, and
improvable by replacing or retraining the model that made it.

---

## 3. A capability is separate from its implementation

model_type names a capability: img2txt, text-embedding, http.
model_name, with its provider, names one implementation of it. Two
implementations of one capability are interchangeable from the caller's
point of view: a step declaring img2txt keeps its shape whether the
model behind it has three billion parameters or seven.

Provider is a dispatch key for how an implementation is obtained and
run. huggingface names downloaded weights; tools names typed code with
no weights, executed the same way -- queued, dispatched, persisted. The
guarantees a result carries, such as whether it can be cached, follow
from the provider.

Implication: reaching outside the protocol for live data needs a new
capability or a new implementation, never a special case in the layer
that composes them.

---

## 4. A boundary enforces structure and leaves meaning to the caller

What crosses a boundary determines what the recipient can do with it.
A text string carries the sender's encoding of meaning; a vector
carries a position in a space the recipient interprets by its own
architecture.

Structural agreement between an input and a handler's expected format
is checkable at the boundary and enforced there. Whether the input's
origin or meaning suits the target is the caller's responsibility.

Implication: request schemas are strict and validated at the API.
Semantic fitness is measured by evals, never assumed by the platform.

---

## 5. The eval is the task specification

A labelled dataset is a formal statement of what a pipeline must
produce. Without one there is no definition of correct behaviour:
outputs cannot be verified, model selection cannot be justified, and
performance cannot be measured.

A labelled example is an input, the output a model produced, and a
correction or confirmation. Accumulated examples characterise the
pipeline's output distribution; an eval run measures against it.

Implication: evals are a product of production use. Every corrected
output refines the specification.

---

## 6. Separation and isolation are what let it scale

The platform, the package and the application are separate, with
separate lifecycles. The platform serves models and is shared by every
application on a host. A package declares what an application needs.
An application is code running in its own container.

Each component owns what it writes and reads everything else. Two
components face outward: the cache container brings artefacts in, and
the API lets requests in. Nothing else crosses the edge. Networks,
mounts and database access follow the same lines, so a boundary in the
design is a boundary in the running system, and a failure stays where
it happens.

Because the layers meet only at declared interfaces, each scales on its
own terms. Ten agents share one worker on a single local GPU; the same
package runs unchanged against many workers.

Implication: nothing reaches across a boundary for convenience.
Application code never runs on the host, never mounts the Docker
socket, and never touches the database.

---

## 7. A package declares requirements, not execution

A package states which models must be present and what its application
runs. It does not say where models execute, on what hardware, or by
which worker. A cached model with no application is valid; an
application using a model cached for another is valid.

The catalogue records what the cache contains. A row is written when
weights are confirmed present, and at no other time.

Implication: execution details stay out of models.yaml, and the
platform can change how models run without any package changing.

---

## 8. Model history drives improvement

Every inference records timing, token counts and memory against the
model, the user and the application that asked. That history supports
billing, but its primary value is a record of how models behave over
time: which are slow, which fail, which applications depend on which
models.

Implication: decisions about replacing, reconfiguring or retiring a
model are made from recorded behaviour, not inspection of individual
jobs.
