# Marigold -- Project Principles

These principles record the reasoning behind recurring design decisions.
They are intended to guide new feature development and to explain why the
system is built the way it is, not merely what it does.

---

## The fat protocol

Marigold is an expression of the Fat Protocol Thesis applied to neural
networks. Model weights are the fat layer: learned, generalised, and opaque.
Typed operations -- a triple of capability class, model, and input set -- are
the protocol primitives. Each operation produces an immutable result drawn
from the distribution the model defines over its inputs.

Workflows compose typed operations into directed fact dependency graphs. Each
step conditions on the outputs of prior steps, forming a chain of extracted
facts. The workflow is a declaration of intent over this composition surface;
the protocol fulfils it. Applications are thin clients over that surface: they
declare a composition, reference the results, and require no knowledge of
execution, ordering, or coordination.

Because results are samples from model distributions, they are non-deterministic.
Applications must be designed to be robust to this. Evals are the protocol's
mechanism for shaping and controlling output distributions: they characterise
what a typed operation actually produces across many samples, and provide the
empirical basis for application design.

---

## All computation is model inference

No custom classifiers, no regex-based routing, no hard-coded rule sets or
keyword lists. Every branch condition, classification, quality gate, and
scoring decision in a pipeline is the output of a model trained on data.
Custom code handles data flow -- routing, mapping, persistence -- but it
does not make decisions.

This applies to the workflow layer as much as to individual model calls.
A pipeline that classifies a document as restricted does so because a model
assigned it a score above a threshold, not because a rule matched a string.
The consequence is that every decision is inspectable, reproducible, and
improvable by replacing or retraining the model.

This principle governs decision-making within the protocol. It does not
preclude tool steps -- HTTP calls, compute steps, and other non-inference
operations -- which handle data flow and external communication. The
distinction is that tool steps do not make decisions; they move or retrieve
data that inference steps then act on.

---

## The exchange primitive determines the communication model

The unit exchanged at a boundary determines what the recipient can do with it.
A text string carries the sender's encoding of meaning into a human symbol
system. A vector carries a position in a geometric space of relationships.
The recipient interprets a vector according to its own architecture and
purpose; the sender's intent is not part of the contract.

---

## Syntactic compatibility and semantic compatibility are separate concerns

Structural agreement between an input and a handler's expected format is
checkable at the API boundary and enforced there. Whether the input's origin
or meaning is appropriate for the target is a caller responsibility. The
system enforces the former and is silent on the latter.

---

## The eval is the task specification

A labelled dataset is a formal statement of what a pipeline is required to
produce. Without one, a pipeline has no definition of correct behaviour:
outputs cannot be verified, model selection cannot be justified, and
performance cannot be measured.

A labelled example is a triple: an input, the output a model produced, and
a correction or confirmation from a human or reference system. Accumulated
triples form a distribution over the pipeline's output space. An eval run
measures the pipeline against that distribution.

This makes evals a first-class output of production use, not a testing phase.
Every corrected output is a labelled example. Every labelled example refines
the task specification. The specification is complete when the distribution
is sufficiently characterised for the application's requirements.
