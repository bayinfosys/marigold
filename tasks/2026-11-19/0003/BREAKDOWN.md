# Breakdown

1. Define ModelSettings: load_in_4bit, use_fast, trust_remote_code
   and low_cpu_mem_usage as optional booleans; extra keys allowed.
2. Replace extra_env on the catalogue item with settings; remove the
   string validator.
3. Apply settings to the environment: names upper-cased, booleans as
   true/false, other values as strings.
4. Update the handler docstrings, the API field description and
   applications.md.
