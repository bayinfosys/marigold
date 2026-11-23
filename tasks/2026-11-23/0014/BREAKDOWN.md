# Breakdown

1. Read each handler setting from self.settings in txt2img, txt2vid,
   img2vid, vid2vid, vid2txt, obs2act, txt2audio, image_embed and tts.
2. Remove set_model_config_env, _ENV_KEYS and _applied_keys from
   shared/db_models.py, and their calls in resident_model and
   tools/model_cache_shared.py.
3. Change the naming rule's wording in shared/model_settings.py,
   building.md and configuration.md: a setting's name stays as it is,
   and it reaches the loader and the handler as a value, not as an
   environment variable.
