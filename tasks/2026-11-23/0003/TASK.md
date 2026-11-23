# [environment] keys the platform sets

The host config and an application config reject an [environment] key
that HostConfig.compose_env() sets from another section, such as
MARIGOLD_API_PORT or MARIGOLD_MODEL_SETTINGS. The error names the key
and the file that sets it in [environment].

Effects:

- an application cannot replace a platform variable, so the host's
  precedence over the application for model settings holds
- the error comes when the config loads, before compose runs
- configuration.md states the rule
