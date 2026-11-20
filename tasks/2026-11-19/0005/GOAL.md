# grasmere-chat v0.0.3

Repository: bayinfosys/grasmere-chat

grasmere-chat moves to marigold 0.8.3. Its registry address becomes
grasmere.marigold.run, its publish workflow is pinned to
registry.yml@v0.8.3, and the evals send a per-run nonce so repeated
runs sample afresh. The release is tagged v0.0.3.

Effects:

- the blog's install commands run against a registry built with a
  released marigold
- eval runs are not answered from the results cache
- the applications page lists v0.0.3
