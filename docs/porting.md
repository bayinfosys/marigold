---
title: Porting an application
description: Bringing an existing AI application to Marigold -- replacing its own model server or machine-learning container with the platform API, with Open WebUI as the worked example.
nav_order: 4
---

# Porting an application

Most self-hosted AI applications carry their own model layer: a bundled
model server, a machine-learning container, model downloads at start-up,
a GPU of their own. Run three of them on one machine and there are three
copies of the same embedding model, issues with resource contention and so on.

Porting an application to Marigold removes that friction. The application
keeps its code, its interface and its data; its model calls go to the
platform API instead. It then shares one model cache and one queue with
every other application on the host, and moves from a laptop to a cloud
account unchanged.

## What maps to what

| In the application | On Marigold |
|---|---|
| a bundled model server (Ollama, llama.cpp, vLLM) | the OpenAI-compatible endpoints, `/v1/chat/completions` and `/v1/embeddings` |
| a machine-learning container: CLIP, captions, faces, OCR | the typed routes: `/embed/image`, `/gen/img2txt`, `/eval/image`, and the rest in [Model types](model-types.md) |
| models downloaded at start-up | `models.yaml`, downloaded by `marigold cache populate` |
| a GPU reserved by the application | nothing: the platform's workers own the GPUs |
| its own database | its own database, kept in the application's directory |

## Steps

1. **Find the model calls.** Most applications already speak the OpenAI
   API for chat and embeddings, and take a base URL. Point it at
   `$MARIGOLD_API_BASE/v1`. Calls to a dedicated machine-learning
   service map to the typed routes; see [API](api.md).
2. **Turn off the application's own downloads.** Disable model
   auto-download and anything that reaches a model hub at start-up, so
   the application runs offline against the platform.
3. **Declare the models.** List every model the application calls in
   `models.yaml`, under the names it requests them by. These are the
   models `cache populate` fetches and the catalogue serves.
4. **Keep its data in the cache.** The application's state belongs
   under the cache directory, so that one directory still holds
   everything.
5. **Package it.** A `marigold.toml`, the `models.yaml`, a README; see
   [Building](building.md). Publish it in your own registry; see
   [Publishing](publishing.md).

## Worked example: Open WebUI

Open WebUI is a chat interface with document retrieval. Standalone, it
expects a model server beside it and downloads an embedding model for
retrieval. On Marigold, both go through the platform.

**The model calls.** Chat and retrieval embeddings both speak the OpenAI
API:

```yaml
OPENAI_API_BASE_URL: http://api:8000/v1
RAG_EMBEDDING_ENGINE: openai
RAG_OPENAI_API_BASE_URL: http://api:8000/v1
RAG_EMBEDDING_MODEL: sentence-transformers/all-minilm-l6-v2
```

**Its own downloads, off.**

```yaml
OFFLINE_MODE: "true"
HF_HUB_OFFLINE: "1"
RAG_EMBEDDING_MODEL_AUTO_UPDATE: "false"
RAG_RERANKING_MODEL_AUTO_UPDATE: "false"
```

**The models**, under the names Open WebUI requests:

```yaml
models:
  - { name: qwen/qwen3-8b, provider: huggingface, type: instruct }
  - { name: sentence-transformers/all-minilm-l6-v2, provider: huggingface, type: text-embedding }
```

**Its data**, at `data/webui` under the cache directory.

**The package.** The `chat` application in the
[examples](examples.md) registry is the result: a `marigold.toml` that
adds the `webui` service, and the `models.yaml` above. Every other
application on the host shares its instruct and embedding models.

## Applications with a web interface

An application whose code is a headless process -- an indexer, a
pipeline, a bot -- runs as an instance: set `[execution].image` to its
container image and `[execution].command` to its entry point.

An application that serves its own web interface needs a published
port. Today that comes from a platform service, as `webui` does for
Open WebUI: open an issue on the
[marigold repository](https://github.com/bayinfosys/marigold) to add
one. Services supplied by the application itself are not yet built.

## Listing a port

Publish the port in a registry of your own -- the project behind the
application is the natural home for it -- and open an issue on the
marigold repository to have it listed in the [Showcase](showcase.md).
