## The idea

A Marigold package is a self-contained bundle: one or more `models.yaml`
files declaring what it needs, a `local.env` setting version/state, and
one or more Python scripts that run against that model set -- a
benchmark, a fixed sequence of operations, a workflow.

This isn't a new thing to build. It's a name for a shape that already
exists in this repo: every directory under examples/ (benchmark-llm,
quick-platform-test, chat, simple-rag, agents) already has this form.
None of them were designed as "packages" -- the pattern emerged from
building five things the same way independently. Worth taking that as
a signal the shape is real.

## What a package would formalise

- **Package deployment.** The bundle (zip, tar, whatever) signed and
  distributed from marigold.run -- turns "clone the repo and copy an
  examples/ directory" into an actual distribution mechanism.
- **Model dependency description.** The models.yaml already IS this --
  a package declares what it needs to run, which becomes a capability
  definition: "this package requires an instruct model and an
  image-embedding model" is a statement about what the package can do,
  derivable directly from what's already in the file.
- **Workflows as the package's exposed tasks.** This is where the
  `workflow` branch (runfox) becomes the mechanism, not a side feature:
  a package's scripts today are ad-hoc Python; a workflow spec is the
  same thing made declarative, executable, and inspectable by anything
  that speaks the workflow API -- not just something you run by hand.

## Why this matters (the "fat protocols for AI" framing)

Packages are where reputation and authority attach. A model file is
just weights; a package is "here is a demonstrated, runnable capability,
built by someone, with a track record" -- the thing people can build a
reputation around and point to, not the underlying model. Marigold
becomes the deployment platform; packages become the units of
capability and authority on top of it.

## Relationship to current work

- The workflow branch (runfox, the six stubbed files, PostgresNotificationBackend)
  is very likely the actual execution engine for a package's exposed
  tasks, once it's rebuilt backend-agnostic. Not urgent now, but worth
  keeping "this is what packages will run on" in mind when that work
  resumes, since it may change some of the priority/shape decisions
  made on that branch.
- reconcile_catalogue's declared-vs-observed pattern (this session) is
  the same shape a package installer would need: declare what a package
  needs, diff against what's present, converge.

## Status

Concept only. Nothing here is designed yet -- no package manifest
format, no signing mechanism, no installer, no relationship between a
package's workflow spec and its models.yaml beyond "they'll probably
need to agree with each other." Worth returning to once the workflow
branch's backend-agnostic rebuild is further along, since package
execution depends on workflows actually running locally.
