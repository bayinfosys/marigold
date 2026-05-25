---
layout: post
title: "Good Practice and Silent Errors in Distributed Inference"
description: "Distributed inference fails quietly. Three practices -- joined observability, consistent container monitoring, and classified error states -- determine whether those failures are findable."
date: 2026-05-21
author: Marigold
category: Engineering
reading_time: 7
canonical: "https://marigold.run/blog/distributed-inference-05-2026/"
og_title: "Good Practice and Silent Errors in Distributed Inference"
og_description: "Distributed inference fails quietly. Three practices determine whether those failures are findable."
schema: |
  <script type="application/ld+json">
  {
    "@context": "https://schema.org",
    "@type": "BlogPosting",
    "headline": "Good Practice and Silent Errors in Distributed Inference",
    "description": "Distributed inference fails quietly. Three practices -- joined observability, consistent container monitoring, and classified error states -- determine whether those failures are findable.",
    "datePublished": "2026-05-21",
    "dateModified": "2026-05-21",
    "author": { "@type": "Organization", "name": "Marigold" },
    "publisher": { "@type": "Organization", "name": "Marigold", "url": "https://marigold.run" },
    "mainEntityOfPage": { "@type": "WebPage", "@id": "https://marigold.run/blog/distributed-inference-05-2026/" }
  }
  </script>
---

# Good Practice and Silent Errors in Distributed Inference

Marigold is a private inference API serving open-weight models on AWS
infrastructure -- LLMs, embedding models, image generation, TTS, ASR.
Heterogeneous models on heterogeneous hardware produces a particular
class of failure: the models are large, the hardware is expensive, and
the errors are quiet.

Three failure modes appear consistently: loading failures, runtime
failures, and routing failures. Each arises from a mismatch between
model, instance, container, and deployment configuration. Each presents
identically from the outside -- slow responses, queues backing up,
containers apparently running. What distinguishes them is not their
symptoms but how they show up under observation. Good practice does not
prevent these failures; it makes them findable.

## Join the data you already have

No failure is visible from a single AWS service. ECS reports task counts.
CloudWatch reports instance metrics. SQS reports queue depth. EFS reports
throughput. Each layer is healthy in isolation; the problem lives in the
relationships between them.

We built a Python dashboard that queries the AWS API across all relevant
layers -- ASG state, ECS container instances, running tasks, SQS queue
depths, EFS throughput, and container log streams -- and joins them into a
single terminal view. Each ASG shows instance type, market type, uptime,
remaining CPU, memory used against total (for example, 14G/31G on a
g4dn.2xlarge, 48G/186G on a g5.4xlarge), GPU availability as free/total,
and task count as running-plus-pending. Below the infrastructure view, the
backlog section shows every model queue with visible message count,
in-flight count, and dead-letter queue depth.

The Marigold cluster spans four ASG types: GPU instances for LLMs and
larger generative models, a CPU-only group (r5.xlarge) for embedding
models and TTS workloads that do not require a GPU, and a test group.
Misrouting -- a GPU-dependent model on a CPU instance, a large LLM on
an instance with insufficient remaining memory -- is invisible without
a view that shows placement and resource utilisation together.

The dashboard collects no new data. It assembles what already exists
across five or six console pages into one view. That assembly is the
practice. Without it, correlating events under pressure means switching
between windows, matching timestamps, and hoping nothing was missed.

## Monitor containers continuously, not just at failure

A container that loads successfully can still fail silently during
operation. The Linux OOM killer terminates processes without writing to
application logs. From the outside, the container stops producing output,
disappears, and ECS replaces it. The replacement loads, runs briefly,
and dies again.

The practice is to structure every container so it produces a consistent
output stream -- metrics, status, routine operational data -- independent
of whether it is processing requests. A container that maintains that
stream is alive and working. One that goes silent has failed. The signal
is the absence of output, not the presence of an error.

In practice this means the failure location is precise. A container that
goes silent during the model load phase has a loading problem. One that
goes silent immediately after load completes, on the first request, has
a runtime problem. We hit this with the Parler TTS model: memory
allocation set to 1 GB, actual footprint closer to 4 GB. ECS placed the
task without complaint because the reservation did not reflect reality.
The container loaded the model, took its first request, and died.

Correct sizing requires accounting for weights at the target quantisation,
generation buffers, and OS overhead. Parler at our configuration needs
approximately 3.5 GB; 4 GB with headroom is the right figure. Both the
ECS memory reservation and the container memory limit should reflect the
real footprint -- a low reservation causes over-placement and RAM
contention; a low limit kills the container. Both failures are silent
without continuous monitoring.

## Classify the error state before diagnosing the cause

The third practice is definitional. Loading failures, runtime failures,
and routing failures share the same surface symptom -- requests not
completing, queues not draining -- but have different causes and different
fixes. Treating them as a single category wastes time and produces
incorrect diagnoses.

A loading failure occurs at cold start. When a deployment triggers
simultaneous cold starts across many containers, EFS contention is the
likely cause. On a standard bursting configuration EFS provides
approximately 100 MB/s shared across all concurrent readers. During a
full production deployment -- the Marigold catalogue runs six smaller
language models, two LLMs, several text embedding models, and four or five
TTS models -- 40 containers sharing that throughput receive 2.5 MB/s each.
A 10 GB model at 2.5 MB/s takes over an hour to load. The CloudWatch
metrics show the failure in sequence: metadata IOPS hits 100% before data
reads begin (all containers performing directory listings simultaneously),
then data read throughput saturates and holds at the ceiling for 30-45
minutes. IOPS utilisation throughout peaks at under 8% -- the constraint
is bandwidth, not operations. An investigation focused on IOPS would
find nothing wrong.

Switching EFS to elastic throughput removes the hard bandwidth ceiling.
The same full deployment that previously saturated the filesystem now
produces three distinct bumps in the throughput trace, each well below
the 75% warning threshold. Bin-packing ECS tasks onto fewer instances
reduces cold loads further -- a model already in the OS page cache from a
previous run reads nothing from EFS at all.

A runtime failure occurs after load. The continuous log stream distinguishes
it from a loading failure by timing: silence after load completion rather
than silence during it.

A routing failure compounds both. With Parler TTS cycling through repeated
OOM kills, SQS messages accumulated delivery counts and stalled. Once the
memory allocation was corrected, the queue drained. The classification
mattered: treating the routing symptom as the primary problem would have
led to queue configuration changes that resolved nothing. The runtime
failure was the cause; the routing failure was the consequence.

## What this means in practice

These three practices -- joining the observability layers, monitoring
containers continuously, and classifying error states before diagnosing
causes -- are not specific to ECS, EFS, or SQS. The same failure modes
appear on Kubernetes with NFS-backed volumes, bare metal with Ceph, and
on-premise GPU clusters. The tools differ; the failure signatures do not.

The underlying principle is the same in each case. If a component is not
instrumented, its failure state is unknown. Unknown failure states produce
misdiagnoses. The practice is to make the invisible visible -- joined,
continuous, and classified -- before anything breaks.

(If you are building private inference infrastructure, [contact us](https://marigold.run/#contact)
to discuss the architecture.)
