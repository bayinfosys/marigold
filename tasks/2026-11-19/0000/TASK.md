# Worker load failures

Applying a model's settings and checking its VRAM become part of the
model load. A failure at either point marks that model failed with a
message naming the cause, and the worker continues serving its other
models. Settings applied for one model are removed before the next
model loads.

Effects:

- a setting that cannot be applied fails one model; the worker stays up
- failed_reason, the 409 response and Open WebUI carry the reason,
  with free and total VRAM for each device
- handler settings such as NUM_STEPS apply only to the model that
  declares them
