# Breakdown

1. Define ModelSettings in its own module under shared/:
   load_in_4bit, use_fast, trust_remote_code and low_cpu_mem_usage as
   optional booleans, with extra keys allowed.
2. Replace extra_env on ModelCatalogueItem with settings, and remove
   the extra_env validator.
3. Apply settings to the environment in set_model_config_env: names
   upper-cased, booleans as true/false, other values as strings.
4. Update the handler docstrings and the API field description that
   mention extra_env.
5. Document `settings:` and the naming rule in applications.md.
