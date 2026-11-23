# Breakdown

1. Add a function to cli/host_config.py that returns the names
   compose_env() sets for a config with no [environment], plus
   AWS_DEFAULT_REGION, which it sets only when [storage] region is set.
2. Reject a reserved key in the host config's [environment] when
   parse_host_config validates it, naming marigold-host.toml.
3. Reject a reserved key in an application config's [environment] when
   validate_application_config validates it, naming marigold.toml.
4. State the rule under [environment] in configuration.md and
   regenerate it.
