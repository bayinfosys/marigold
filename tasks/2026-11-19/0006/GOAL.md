# marigold-examples settings

Repository: bayinfosys/marigold-examples

The example applications move to marigold 0.8.3: model entries that
use extra_env declare `settings:` instead, and the publish workflow is
pinned to the release. The registry is tagged with a new version.

Effects:

- benchmark-image-gen, benchmark-llm, chat and simple-rag install and
  load with marigold 0.8.3
- the examples show the settings vocabulary new applications follow
