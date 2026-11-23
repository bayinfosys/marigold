# Loaders receive their settings

The worker passes the resolved ModelSettings to the handler, and the
handler passes it to its loader. standard_loader reads load_in_4bit,
use_fast, trust_remote_code and low_cpu_mem_usage from it; the txt2img
loader reads load_in_4bit, diffusers_quant_components and
diffusers_device_map, and passes the device map to
load_diffusion_pipeline as an argument. cache-init passes its own
resolution, with load_in_4bit off. ModelSettings.get returns a typed or
extra setting, or a default. env_flag stays for HF_HUB_OFFLINE, a
platform variable, and reads no model setting.

Effects:

- a loader's settings are its arguments
- the settings resolved for a load are the settings the loader uses,
  with nothing between them
