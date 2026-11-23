# Handlers read their settings

Each handler reads its settings from self.settings, with the same
defaults: num_steps, keyframe_mode, max_input_frames, input_mode,
max_frames, action_dim, prompt_template, proprioception_mode,
num_inference_steps, precision and model_langcode.
set_model_config_env goes, with the environment variables it wrote.

Effects:

- no model setting passes through the process environment
- a handler's inputs are its arguments
- building.md and configuration.md describe settings as values passed
  to the loader and the handler

Depends on 0013.
