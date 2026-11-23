# Loaders receive their settings

The worker passes the resolved ModelSettings to the handler, and the
handler passes it to its loader. standard_loader reads load_in_4bit,
use_fast, trust_remote_code and low_cpu_mem_usage from it;
load_diffusion_pipeline reads diffusers_device_map; the txt2img loader
reads load_in_4bit and diffusers_quant_components. cache-init passes
its own resolution, with load_in_4bit off. env_flag goes.

Effects:

- a loader's settings are its arguments
- the settings resolved for a load are the settings the loader uses,
  with nothing between them
