# Breakdown

1. Give BaseModelHandler.__init__ a settings argument: store it as
   self.settings and pass it to the loader. Pass it through each
   handler's __init__.
2. Construct the handler in resident_model with the resolved settings.
3. Add ModelSettings.get. Read the loader settings from the settings
   argument in standard_loader and the txt2img loader; give
   load_diffusion_pipeline a device_map argument in place of its
   environment read.
4. Pass the settings through every loader that calls standard_loader;
   the loaders take keyword arguments and pass them on.
5. Pass cache-init's resolved settings to the loader in
   tools/model_cache_shared.py.
