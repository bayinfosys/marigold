# Breakdown

1. Give BaseModelHandler.__init__ a settings argument: store it as
   self.settings and pass it to the loader. Pass it through each
   handler's __init__.
2. Construct the handler in resident_model with the resolved settings.
3. Read the loader settings from the settings argument in
   standard_loader, load_diffusion_pipeline and the txt2img loader, and
   remove env_flag.
4. Pass the settings through every loader that calls standard_loader.
5. Pass cache-init's resolved settings to the loader in
   tools/model_cache_shared.py.
