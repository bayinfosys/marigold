# Marigold -- Pricing Model

This document records the reasoning behind Marigold's pricing structure.
It is intended as a reference for internal decision-making, investor
conversations, and commercial negotiations.

---

## The core observation

Flat-rate inference pricing works when usage is human-paced. It does not
work when usage is machine-paced.

A person using an AI API through an IDE, a web interface, or an occasional
script is rate-limited by their own cognitive speed. They cannot send
requests faster than they can think. The variance in their monthly usage
is low, predictable, and well below the cost of the infrastructure serving
them.

An autonomous agent running continuously has no such constraint. A single
agent loop can consume GPU capacity worth multiples of any reasonable flat
monthly fee within hours. The tokenmaxxing problem -- where a single
customer saturates shared infrastructure -- is not a billing edge case;
it is the designed behaviour of agentic workloads. Flat-rate pricing for
agents either caps the agent (defeating its purpose) or is not viable at
the infrastructure cost.

Marigold's pricing structure acknowledges this directly rather than
obscuring it behind seat counts or token allowances.

---

## The three tiers

### Human -- flat rate

Human-paced interactive use. IDE assistants, manual API calls, exploratory
development. The request rate is bounded by the user's presence at a
keyboard. Shared CPU infrastructure is sufficient. The flat monthly rate
is sustainable because the consumption ceiling is biological.

This tier is the funded entry point. It covers its infrastructure cost,
generates product feedback, and qualifies users for the tiers above.

### Developer -- flat rate

Automation and pipeline development. Scheduled jobs, eval runs, batch
processing initiated by a human but not requiring their presence during
execution. GPU access is included. Usage is bursty rather than continuous;
the human is still in the loop deciding when workloads run, even if they
are not watching them.

Flat rate remains sustainable here because the initiation pattern is
still human-driven. A developer does not typically run a GPU pipeline
continuously; they run it, review the results, and run it again. The
natural rhythm of development work provides sufficient back-pressure.

### Agentic -- provisioned capacity

Production systems running without human initiation. Agent loops, live
pipelines, systems where continuous inference is the product. The whole
point of this tier is that there is no human in the request path.

This tier is priced as provisioned capacity, not a flat rate:

- A monthly minimum acts as a retainer that reserves dedicated GPU
  infrastructure. This is a commitment, not a cap.
- Usage scales with the workload up to an agreed ceiling, negotiated
  per account.
- Capacity is exclusive: the customer's agents are never queued behind
  other customers' workloads. There is no shared pool.
- Accounts that consistently use significantly below their provisioned
  capacity are moved to the Developer tier. The reservation only exists
  while the capacity is being used.

The downgrade clause is structurally important. It prevents a backlog of
underutilised reservations, keeps AWS costs tied to actual revenue, and
ensures dedicated capacity is available to customers who genuinely need it.

---

## The commercial structure

Marigold operates at the API layer above commodity GPU compute. The
underlying resource -- GPU hours on AWS -- is a commodity and is priced
as such. What Marigold provides above that layer is not:

- A typed inference API covering instruct, embedding, TTS, image-to-text,
  depth, segmentation, and eval model types.
- A pre-loaded model registry with weight caching on EFS, eliminating
  cold-start latency per model.
- An OpenAI-compatible endpoint requiring no client-side code changes.
- A declarative YAML workflow engine composing model calls into pipelines.
- An eval surface for measuring output quality against production data.
- UK and EU data residency with no third-party model provider in the
  inference path.
- The operational burden of running, scaling, and maintaining all of it.

A customer building this themselves on AWS would spend weeks reaching
the same starting point and then own the maintenance permanently. The
Agentic tier customer is not paying for GPU hours; they are paying for
not having to build or operate the layer above the GPU.

---

## Revenue structure

The three tiers have distinct commercial roles:

Human and Developer are the qualified pipeline. They generate catalogue
feedback, surface integration patterns, produce case studies, and cover
their own infrastructure cost. Their primary commercial function is to
qualify customers for the Agentic tier, not to be the primary revenue
source.

Agentic is the business. A customer with production agent pipelines
running against Marigold's API is not a one-afternoon migration away
from a competitor. The integration layer -- model names, workflow YAML
format, eval surface, API shape -- creates switching cost above and
beyond the compute itself.

Revenue scales with usage. Because Agentic billing is provisioned rather
than flat, increased agent activity by existing customers directly
increases revenue without requiring new customer acquisition. The
commodity supply model -- buy GPU capacity from AWS at cost, deliver
it through the Marigold API layer with margin -- means volume is the
primary lever on profitability.

---

## The reservation dynamic

Customers on the Agentic tier have an incentive to maintain their
reservation rather than relinquish it. Dedicated GPU capacity at
scale is not always available on demand. A customer who gives up their
reservation and later needs to scale back up may face a queue or a
capacity constraint.

This is a natural property of any reservation market -- airline seats,
cloud reserved instances, co-location racks -- and it operates in
Marigold's favour without requiring any explicit lock-in mechanism. The
customer retains the reservation because the alternative (losing access
to guaranteed capacity) carries operational risk for their production
workloads.

The downgrade clause reinforces this: the tier is earned by usage, not
purchased as a right. Customers who value their reservation spend enough
to keep it.

---

## Investment framing

The market position is: private, UK-resident, open-weight inference
infrastructure with a pricing model calibrated to how AI is actually
consumed.

The majority of existing inference API products price by token. This
works for the providers because it transfers infrastructure cost variance
directly to the customer. It does not work well for customers building
production systems, who need cost predictability and capacity guarantees.

The Agentic tier addresses the segment of the market that has outgrown
token billing but is not large enough to justify building and operating
private GPU infrastructure in-house. This segment is growing as AI moves
from experimental to production workloads. The provisioned capacity model
is the correct commercial structure for that segment and is currently
underserved by the major providers, who prioritise high-volume enterprise
contracts over mid-market production deployments.

Marigold's position is defensible at the API and workflow layer above
the commodity GPU. The moat is not the compute; it is the abstraction,
the model catalogue, and the operational reliability delivered on top
of it.
