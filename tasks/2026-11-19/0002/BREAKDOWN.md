# Breakdown

1. Bring down every application project in platform stop before the
   platform; remove --applications from the parser.
2. Validate compose_files in the host config: "gpu" requires "cpu"
   earlier in the list, and the message gives ["core", "cpu", "gpu"].
3. Make the verify name optional: with no name, check every installed
   application, print one line each, and exit 1 when any has changed.
4. Describe [environment] as compose variables that a service receives
   where its compose file names them.
5. Default ENABLE_OLLAMA_API to false in the webui compose file.
6. Update architecture.md and getting-started.md for platform stop,
   installing.md for verify, and regenerate configuration.md.
