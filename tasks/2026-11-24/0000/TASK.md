# One import package, marigold

The seven packages under package/src move to package/src/marigold/,
and every module is imported as `marigold.<name>`.

Effects:

- an install adds one import package, `marigold`, and the `marigold`
  command
- the wheel holds every subpackage, including marigold.api.routes,
  marigold.backend.messaging and marigold.shared.storage
- the api, worker and cache containers start marigold.api.main,
  marigold.models.entrypoint_handlers and marigold.tools.cache_cli
- the cache image's default command runs a module that exists
- no behaviour changes
