---
title: Publishing applications
description: Registries, marigold-registry.toml, building a registry, and publishing it with GitHub Pages or any static host.
nav_order: 4
---

# Publishing applications

Applications are distributed through registries. A registry is a
directory of static files any web server can serve:

```
marigold-applications.json              the index
applications/<name>-<version>.tar.gz    the archives
applications/<name>/                    catalogue pages
llms.txt, sitemap.xml                   discovery
```

The index and the archives are all Marigold reads. The catalogue pages
are for people and search engines.

## A registry repository

```
my-registry/
  marigold-registry.toml
  first-app/
    marigold.toml
    ...
  second-app/
    marigold.toml
    ...
```

Every directory under the root holding a `marigold.toml` is published.
To leave one out, remove its `marigold.toml`. An application inside
another application's directory is an error.

### marigold-registry.toml

```toml
[registry]
title = "My applications"
description = "One sentence saying what this registry holds."

[registry.urls]
repository = "https://github.com/<owner>/<repo>"
```

| Key | Required | Meaning |
|---|---|---|
| `title` | yes | shown on every catalogue page |
| `description` | yes | shown on the front page and in `llms.txt` |
| `urls` | no | links shown in the navigation bar and footer |
| `front_page` | no | a Markdown file of visitor text for the front page |
| `site` | no | a directory of templates laid over the default catalogue |

## Building

```sh
cd my-registry
marigold registry build
```

This writes `dist/`. A rebuild from the same sources produces the same
files. Serve `dist/` directly to test installs against it:

```sh
python -m http.server 8080 -d dist
```

The catalogue pages are Jekyll source. To render them locally:

```sh
docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -v "$PWD/dist":/site ghcr.io/bayinfosys/jekyll-site-builder:v0.0.2
python -m http.server 8080 -d dist/_site
```

Create `dist` yourself before mounting it, so that it belongs to you
and not to root.

## Publishing with GitHub Pages

One-time settings in the registry repository:

1. Settings, Pages, Source: **GitHub Actions**.
2. Settings, Environments, `github-pages`, Deployment branches and tags:
   add a **tag** rule for `v*`.

Add `.github/workflows/publish.yaml`:

```yaml
name: registry

on:
  push:
    branches: ["**"]
    tags: ["v*"]
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: pages
  cancel-in-progress: false

jobs:
  registry:
    uses: bayinfosys/marigold/.github/workflows/registry.yml@v0.8.1
    with:
      marigold-version: "0.8.1"
      site-builder: ghcr.io/bayinfosys/jekyll-site-builder:v0.0.2
      deploy: ${{ startsWith(github.ref, 'refs/tags/v') }}
```

Every push builds the registry, which checks it. Pushing a `v*` tag
publishes it:

```sh
git tag v1.0.0 && git push origin v1.0.0
```

The permissions block is required: GitHub deploys a repository's site
only when that repository's own workflow grants it. A re-run uses the
workflow as it was when the run started, so after changing the
workflow, push a new tag.

To serve the registry from its own domain, set Settings, Pages, Custom
domain, and add a `CNAME` record for that name pointing at
`<owner>.github.io`. The project's registries use subdomains of
`marigold.run`, such as `examples.marigold.run`. The workflow takes the
site address from Pages, so the catalogue's absolute links follow the
custom domain without further changes.

## Publishing elsewhere

The index and archives in `dist/` work without Jekyll: copy the
directory to any static host and installs from it succeed. The
catalogue pages need rendering. To render them in GitHub Actions and
deploy elsewhere, pass `deploy: false` and download the `github-pages`
artifact in a later job.

## The index

```json
{
  "protocol": 1,
  "applications": {
    "my-app": {
      "versions": {
        "0.1.0": {
          "archive": "applications/my-app-0.1.0.tar.gz",
          "sha256": "...",
          "description": "...",
          "requires": []
        }
      }
    }
  }
}
```

Archive paths are relative to the index, so one build works at any
address. Every value is taken from the archive it describes; nothing in
the index is written by hand.

## Customising the catalogue

A `site` directory is laid over the default catalogue: a file there
replaces the default at the same path. Layouts, the stylesheet, the
front page, `llms.txt` and `sitemap.xml` can all be replaced. The
default templates, and the data they read, are in
[package/src/cli/site](https://github.com/bayinfosys/marigold/tree/master/package/src/cli/site).
