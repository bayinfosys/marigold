---
title: Model types
description: Every Marigold model type, its route, input, output and example models.
nav_order: 9
---

# Model types

A model's `type` in `models.yaml` decides how it is loaded, which
route serves it and the shape of its input and output. Binary outputs
are stored as objects and returned as references; see [API](api.md).

| Type | Route | Input | Output | Example models |
|---|---|---|---|---|
| `text-embedding` | `/embed/text` | text | vector | all-minilm-l6-v2, bge-small-en-v1.5 |
| `image-embedding` | `/embed/image` | image | vector | clip-vit-base-patch32 |
| `instruct` | `/gen/instruct` | chat | chat | qwen3-0.6b, qwen2.5-3b-instruct |
| `img2txt` | `/gen/img2txt` | image | text | smolvlm-256m-instruct, paligemma2 |
| `txt2img` | `/gen/txt2img` | text | image (png) | stable-diffusion-3.5-large-turbo, flux.1-schnell |
| `img2mask` | `/gen/img2mask` | image | segmentation mask (png) | sam-vit-huge |
| `depth` | `/gen/depth` | image | depth map (png) | dpt-dinov2-small-kitti |
| `tts` | `/gen/tts` | text | audio (mp3) | mms-tts-eng, mms-tts-cym |
| `txt2audio` | `/gen/txt2audio` | text | audio (mp3) | musicgen-small, audioldm2 |
| `asr` | `/gen/asr` | audio | text, with segment timings | whisper-tiny, whisper-small |
| `txt2vid` | `/gen/txt2vid` | text | video (mp4) | CogVideoX-2b, Wan2.1-T2V-1.3B |
| `img2vid` | `/gen/img2vid` | image keyframes | video (mp4) | stable-video-diffusion, Wan2.1-I2V |
| `text-eval` | `/eval/text` | text | scores | toxic-bert, distilbert-sst2 |
| `text-similarity` | `/eval/text-similarity` | text pair | similarity score | all-minilm-l6-v2 |
| `image-eval` | `/eval/image` | image | scores | nsfw-image-detection, cafe-aesthetic |
| `image-text-eval` | `/eval/image-text` | image and text | alignment score | clip-vit-base-patch32 |

`instruct` and `text-embedding` models are also served on the
OpenAI-compatible endpoints.

The source of this list is `ModelType` in
[package/src/shared/enums.py](https://github.com/bayinfosys/marigold/blob/master/package/src/shared/enums.py),
and the handlers in
[package/src/models](https://github.com/bayinfosys/marigold/tree/master/package/src/models).

## Adding a model type

1. Add a handler in `package/src/models/`, following the existing
   pattern, and register its import in `models/load_all()`.
2. Every handler is registered at import time with the `@model_spec`
   decorator from `shared.registry`. A `ModelSpec` couples the model
   type, the mode (embed, eval, gen), the loader, the handler class
   implementing `_run()`, the request and response models, the binary
   output fields and the route.
3. A loader returns a `ModelLoaderResult(processor, model)`.
   `standard_loader` in `models/standard_loader.py` handles the common
   `AutoTokenizer` / `AutoProcessor` plus `AutoModel` pattern.
4. `BaseModelHandler.process()` validates the request against
   `ModelSpec.request_model` and calls `_run()` with the typed result.
   Subclasses implement only `_run()`.

Adding a model of an existing type needs no code: add it to an
application's `models.yaml`, reinstall the application and run `marigold
cache populate`.
