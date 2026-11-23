# VRAM check for handlers without an nn.Module

check_model_vram accepts the two handler models it rejects: a handler
whose model is None has no weights to place, and a transformers
pipeline is checked through its model.

Effects:

- the http and asr handlers load on a GPU worker
- an http model's placement is empty, and its CPU offload is zero

The other loaders return an nn.Module or a DiffusionPipeline, which the
check already handles (parler-tts and MusicGen models are modules;
AudioLDM2 is a pipeline).
