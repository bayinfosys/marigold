# Bay Information Systems -- Public Writing Terminology

This document records the phrases that should recur across public writing:
articles, LinkedIn posts, the website, and product copy for Marigold. The
aim is recognition. A reader who encounters the same load-bearing phrase
across several pieces begins to associate it with the author.

This is not a glossary. Terms are included because they are doing
argumentative work somewhere in the public writing. Engineering vocabulary
that belongs in internal documents is explicitly kept out of public prose.

---

## Core phrases

### Model weights are the fat layer

The foundation model understood as infrastructure. Borrowed from Joel
Monegro's 2016 essay and applied to AI rather than blockchain. The claim
encoded in the phrase is that value and generality sit in the weights, not
in the applications above them.

### Workflows are thin clients

The counterpart. An application that calls a model does not own the
capability it is using; it is a declaration of intent over a shared
substrate. Pairs with the fat layer claim and should usually appear near
it.

### The eval is the task specification

The labelled dataset is the formal statement of what "correct" means for a
given pipeline. This reframes evals from a downstream quality gate to the
primary artefact of any engagement.

### Data plus labels plus model equals evals

The compact form of the same claim. Useful as a pull-quote or a sentence
that can stand alone. Avoid writing it as a formal equation unless the
surrounding context is technical.

### All computation is model inference

Marigold's governing constraint, but the phrase travels. It makes a
falsifiable claim: no regex branches, no hard-coded rule sets, no custom
classifiers. Every decision in a pipeline is the output of a model that
can be inspected, replaced, or retrained. Use when writing about pipeline
architecture, decision inspectability, or why conventional business logic
fails in AI systems.

### Typed operations

The unit of work at the protocol layer: a capability class (text-to-embedding,
image-to-text, text-to-speech), a model, and an input set. Concrete enough
to carry itself in prose without definition. Use in preference to "API calls"
or "model invocations" when the distinction matters.

### Non-deterministic outputs / samples from a distribution

Two phrases for the same observation. Prefer "samples from a distribution"
in technical prose; "non-deterministic outputs" in copy aimed at a less
specialist audience. Both are more precise than "what the model says" or
"the model's answer".

### Syntactic and semantic compatibility

A distinction worth keeping even though the words are formal. Syntactic
compatibility is whether the shape matches: the input has the right type,
the right fields, the right units. Semantic compatibility is whether the
meaning is right: the input is the kind of thing the handler is supposed
to receive, from a source that makes sense. The system can check the first
at an API boundary. The second is the caller's responsibility. The
distinction recurs in contexts beyond the obvious (data pipelines,
integration boundaries, agent handoffs) and is likely to accumulate meaning
over time.

---

## Phrases to avoid

### "Directed fact dependency graph"

Internally correct. Publicly opaque. Replace with "workflow" or "a chain
of steps where each depends on the previous".

### "Composition surface"

Engineering shorthand. In prose: "the set of operations a workflow can use"
or simply "what the protocol exposes".

### "Protocol primitive"

Acceptable inside the Fat Protocol article, which sets it up. Elsewhere,
"typed operation" usually covers it.

### "Exchange primitive"

Replace with "the unit passed between steps" or "what one step hands to
the next".

### Generic SaaS register

"Unlock", "leverage", "empower", "seamless", "robust solution",
"cutting-edge". The voice rules already rule these out; they are listed
here as a reminder that the temptation recurs when writing product-adjacent
copy.

---

## Usage notes

Repetition matters more than variation. If "the fat layer" is the right
phrase, use it repeatedly across articles rather than rotating through
synonyms. Consistency is how recognition accumulates.

New terms should enter this document before they enter the second article
that uses them. A phrase used once is prose; a phrase used twice is
vocabulary and should be deliberate.

A term enters the core list when it has done argumentative work in at least
one published piece and has a clear reusable formulation. Speculative
terminology stays in the principles document until it has earned a public
formulation.
