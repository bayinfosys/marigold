# Loader errors carry their cause

ModelNotFoundError's message includes the exception the loader raised:
the model name, the exception type and its message.

Effects:

- failed_reason, the 409 a client receives and `marigold models inspect`
  say why a model failed to load
