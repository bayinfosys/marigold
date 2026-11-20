# Breakdown

1. Bring down application projects in platform stop unconditionally;
   remove the flag from the parser and the docs.
2. Validate compose_files: "gpu" requires "cpu" earlier in the list.
3. Make the verify name optional: with no name, check every installed
   application and exit 1 when any has changed; note it in
   installing.md.
4. Correct the [environment] field description and regenerate
   configuration.md.
5. Default ENABLE_OLLAMA_API to false in the webui compose file.
