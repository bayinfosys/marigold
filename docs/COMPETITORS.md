# Competitors

This document tracks the competitive landscape across two segments:
model inference providers, and workflow automation platforms. It is not
exhaustive but covers the principal peers and points of differentiation.

Marigold distinguishes itself from inference providers by its typed operation
protocol, async job architecture, workflow composition layer, and EU (eu-west-2)
jurisdiction. It distinguishes itself from workflow platforms by hosting model
weights directly, enforcing typed inputs and outputs at the protocol level, and
pricing on compute consumed rather than operations counted.

Last reviewed: May 2026

---

## Inference and model hosting providers

Columns:

- Weights: whether the provider runs open-weight models, proprietary models,
  or both
- Task breadth: LLM-only, multimodal (LLM + image/video), or broad
  (includes embeddings, TTS, depth, segmentation, tabular, etc.)
- Execution: synchronous (request/response), asynchronous (job queue /
  polling), or both
- Workflow layer: whether the platform exposes any pipeline composition
  primitive natively
- EU jurisdiction: whether inference can be contractually pinned to EU
  data centres

| Provider              | HQ / Jurisdiction     | Weights       | Task breadth      | Execution | Workflow layer      | EU jurisdiction | Notes                                                                                 |
|-----------------------|-----------------------|---------------|-------------------|-----------|---------------------|-----------------|---------------------------------------------------------------------------------------|
| Together AI           | US                    | Open          | Multimodal        | Sync      | None                | No              | Large open-weight catalogue; competes on $/token; async batch endpoint added 2025     |
| Fireworks AI          | US                    | Open          | Multimodal        | Sync      | None                | No              | Fast inference; function calling focus                                                |
| Groq                  | US                    | Open          | LLM only          | Sync      | None                | No              | Custom LPU silicon; throughput leader for supported models                            |
| Cerebras              | US                    | Open          | LLM only          | Sync      | None                | No              | Wafer-scale chip; very high token throughput on small models                          |
| SambaNova             | US                    | Open + prop.  | LLM only          | Sync      | None                | No              | Custom RDU hardware; enterprise focus                                                 |
| Hyperbolic            | US                    | Open          | Multimodal        | Sync      | None                | No              | Commoditised GPU rental framed as inference API                                       |
| Novita AI             | US / CN               | Open          | Multimodal        | Sync      | None                | No              | Broad model catalogue including image gen; GPU instances also available               |
| fal.ai                | US                    | Open          | Broad             | Async     | None                | No              | Serverless image/video/audio/3D; proprietary inference engine; async job+webhook model; strong image gen throughput |
| WaveSpeedAI           | US                    | Open          | Broad             | Async     | None                | No              | Image/video focus; exclusive ByteDance/Alibaba model partnerships (Kling, Seedream)   |
| Runware               | US                    | Open          | Image only        | Async     | None                | No              | Ultra-low cost image generation ($0.0006/image); raised $50M 2025                    |
| Replicate             | US                    | Open          | Broad             | Async     | None                | No              | Async job model; 1000+ community models; strong image/video/audio coverage; no workflow layer |
| SiliconFlow           | CN                    | Open + prop.  | Broad             | Both      | None                | No              | Chinese-based; 200+ models; LLM, image, video, audio; 100B+ daily tokens; Huawei Ascend chip support; not EU-appropriate for sensitive data |
| Featherless.ai        | US / Canada           | Open          | LLM only          | Sync      | None                | No              | 30,000+ open models; flat-rate pricing; founded by RWKV team; $20M Series A (AMD Ventures, Airbus Ventures) Apr 2026 |
| Modal                 | US                    | Open          | Broad             | Both      | Cron / scheduled    | No              | Python-native serverless GPU; developer-oriented; no typed ops                        |
| Baseten               | US                    | Open          | Broad             | Sync      | None                | No              | Model deployment platform; custom model serving                                       |
| Beam                  | US                    | Open          | Broad             | Async     | None                | No              | Serverless GPU functions; developer-oriented                                          |
| RunPod                | US                    | Open          | Broad             | Both      | None                | Partial         | GPU cloud with serverless endpoint option; raw infrastructure                         |
| Northflank            | UK                    | Open          | Broad             | Both      | None                | Yes             | Full-stack GPU infra (databases, queues, APIs, model endpoints in one platform); BYOC; UK-based; enterprise focus |
| DeepInfra             | US                    | Open          | LLM + embed       | Sync      | None                | No              | Low-cost LLM and embedding inference                                                  |
| Cloudflare Workers AI | US (global edge)      | Open          | LLM + embed + img | Sync      | None                | Partial         | Edge inference; low latency; limited model range; no GPU-class tasks                  |
| NVIDIA NIM            | US (self-hosted)      | Open + prop.  | Broad             | Sync      | None                | Self-host       | Containerised inference microservices for self-hosting on NVIDIA GPUs; enterprise licensing; not a managed API |
| nscale                | UK                    | Open          | LLM only          | Sync      | None                | Partial         | UK-based; EU data residency available; LLM focus only                                 |
| Scaleway              | France / EU           | Open          | LLM + speech      | Sync      | None                | Yes             | EU-native; GDPR; data residency as primary pitch; model range narrow but growing      |
| OVHCloud              | France / EU           | Open          | LLM only          | Sync      | None                | Yes             | EU-native; enterprise pricing; model range narrow                                     |
| Mistral AI            | France / EU           | Proprietary   | LLM only          | Sync      | None                | Yes             | EU-native proprietary LLM; strong on European enterprise compliance                   |
| Cohere                | Canada / US           | Proprietary   | LLM + embed       | Sync      | None                | No              | Enterprise NLP focus; strong embedding and rerank products                            |
| AWS Bedrock           | US (multi-region)     | Both          | Multimodal        | Both      | Via Step Functions  | Yes (opt-in)    | Managed; integrates with AWS ecosystem; workflow via separate product                 |
| Azure AI Foundry      | US (multi-region)     | Both          | Multimodal        | Sync      | Limited             | Yes (opt-in)    | Enterprise managed; pipeline tooling shallow; proprietary lock-in                     |
| Google Vertex AI      | US (multi-region)     | Both          | Multimodal        | Both      | Vertex Pipelines    | Yes (opt-in)    | Deepest pipeline tooling among hyperscalers; still LLM-centric                        |
| HuggingFace Inference | US / EU               | Open          | Broad             | Sync      | Spaces (limited)    | Partial         | Distribution layer over partner providers; no direct compute                          |
| Dify                  | US / open source      | Via proxy     | LLM + embed       | Both      | Visual (LLM-only)   | Self-host       | Closest peer with both workflow and model routing; async via Celery/Redis; no typed ops; no non-LLM task types |
| Lepton AI             | US                    | Open          | LLM only          | Sync      | None                | No              | Developer-oriented; Kubernetes-based; limited model range                             |

---

## Workflow automation platforms

These platforms can invoke AI models via third-party API calls. They do not
host model weights or enforce typed operation contracts. They are competitors
on the workflow composition surface only.

A structural observation: the cost pathologies reported by practitioners
(polling overhead, pre-filter execution, iterator multiplication, AI calls
in high-frequency paths) are consequences of architecture, not product
maturity. Platforms built around trigger-step-action primitives with per-
operation billing have no mechanism to distinguish a cheap filter from an
expensive model call, or to batch, cache, or defer work. These are not
fixable with better user configuration; they are inherent to the model.

Marigold's async queue architecture, typed operations, and result caching
(DynamoDB keyed by input hash) address these at the infrastructure level
rather than requiring the caller to design around them.

Columns:

- AI integration: API call only (user configures HTTP node), native AI
  nodes (pre-built integrations with LLM providers), or model hosting
  (weights run on the platform)
- Execution model: event-driven, polling-based, or code-defined
- Billing unit: per task/operation, per successful outcome, or compute-based
- Self-hostable: whether an on-premises or private cloud deployment is
  available

| Product         | HQ / Jurisdiction     | AI integration      | Execution model          | Billing unit           | Self-hostable | Notes                                                                                          |
|-----------------|-----------------------|---------------------|--------------------------|------------------------|---------------|------------------------------------------------------------------------------------------------|
| Zapier          | US                    | Native AI nodes     | Event / polling          | Per task               | No            | Largest integration catalogue; expensive at volume; no batch primitives                        |
| Make            | Czech Rep. / EU       | Native AI nodes     | Event / polling          | Per operation          | No            | More flexible than Zapier; same per-operation cost model at scale                              |
| n8n             | Germany / EU          | Native AI nodes     | Event / polling / code   | Per execution (cloud)  | Yes           | Self-hostable; EU-native; better for developers; polling overhead remains                      |
| Pipedream       | US                    | API call + AI nodes | Event / code             | Per invocation         | No            | Developer-oriented; code steps reduce some overhead; still per-event                           |
| Activepieces    | US / open source      | API call            | Event                    | Per task (cloud)       | Yes           | MIT licence; growing integration set; limited AI-native tooling                                |
| Temporal        | US                    | API call (code)     | Code-defined             | Compute                | Yes           | Durable workflow orchestration for engineers; no visual builder; closest to Marigold's execution model |
| Prefect         | US                    | API call (code)     | Code-defined / scheduled | Compute                | Yes           | Data pipeline focus; Python-native; no AI-native primitives                                    |
| LangChain / LangGraph | US              | Native (LLM-only)   | Code-defined             | Compute (self-run)     | Yes           | AI workflow framework; no model hosting; LLM-centric; no typed ops; widely used as a library   |
| Langflow        | US (Datastax)         | Native (LLM-only)   | Visual / code            | Cloud or self-run      | Yes           | Visual LangChain builder; acquired by Datastax 2025; LLM and RAG focus; no model hosting; 42k+ GitHub stars |
| Flowise         | US / open source      | Native (LLM-only)   | Visual / code            | Self-run               | Yes           | Visual LangChain; no model hosting; LLM and RAG focus only; simpler than Langflow; ~30k GitHub stars |
| Dify            | US / open source      | Native (LLM-only)   | Visual + async (Celery)  | Cloud or self-run      | Yes           | Also appears in inference table; listed here for workflow surface; 58k+ GitHub stars; restrictive SaaS licence |
| Haystack        | Germany / EU (deepset)| Native (LLM-only)   | Code-defined             | Compute (self-run)     | Yes           | EU-native; pipeline framework for NLP/RAG; production-grade; engineer-oriented; deepset Studio adds visual layer |
| ZenML           | Germany / EU          | API call (code)     | Code-defined / scheduled | Compute                | Yes           | MLOps pipeline orchestration; EU-native; pairs with LangGraph/LlamaIndex for agentic flows     |

---

## Notes on overlap

No platform in either table does all of: a typed operation protocol across
non-LLM model classes, async job architecture, workflow composition, and EU
jurisdiction in a single product.

The closest structural peers on the inference side are fal.ai (async,
broad task types, no workflow) and Replicate (async, broad, no workflow).
On the workflow side, Temporal is the closest match to Marigold's execution
model but requires the caller to write all model integration by hand and
provides no model hosting.

Dify spans both tables: it has a workflow builder and proxies model APIs.
It does not host weights, has no typed operation contract, and its
multi-tenant SaaS use requires a commercial licence.
