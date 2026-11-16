---
title: Manifests and digests
description: How Marigold identifies an application by its files -- the manifest format, the digest, and how to compute both with standard tools.
nav_order: 5.5
---

# Manifests and digests

An application is identified by its files. Its manifest lists every
file with its mode and sha256; its digest is the sha256 of the
manifest. Equal digests mean equal files, whatever the archive bytes or
the version label.

The manifest is never stored or published. Each step computes it from
the files in front of it, and they agree:

| Step | Computes the manifest of | Does with the digest |
|---|---|---|
| `application create` | the source directory, then the archive written from it | refuses an archive whose files differ; prints the digest |
| `registry build` | each published archive | records it in the index as `digest` |
| `application install` | the installed files | records it in `installed.json`; refuses a mismatch with the index |
| `application verify` | the installed files | compares with the recorded digest |
| `application diff` | both sides | lists added, removed and changed files |

Digests are shown as their first 12 characters, as git shows commits.
Everything stored holds the full 64.

## The format

One line per file, sorted by path:

```
<mode> <sha256>  <path>
```

```
100644 5c22...80  README.md
100755 a07b...12  bin/run.sh
100644 91de...4c  marigold.toml
100644 e3b0...55  models.yaml
```

- **mode** is git's: `100755` when the file's owner may execute it,
  `100644` otherwise.
- **sha256** is of the file's bytes as they are, with no line-ending
  conversion.
- **path** is relative to the application root, `/`-separated, UTF-8.
- Lines are sorted by the path's bytes, and every line ends in a
  newline.

The digest is the sha256 of the manifest text.

## Which files

Every regular file under the application root, hidden files included,
as git does, except:

- these names, wherever they appear in a path: `.git`, `.hg`, `.svn`,
  `__pycache__`, `.venv`, `venv`, `node_modules`, `.mypy_cache`,
  `.pytest_cache`, `.ruff_cache`, `.DS_Store`, `dist`, `build`, `.env`;
- these suffixes: `.pyc`, `.pyo`, `.tar.gz`, `.tgz`, `.marigold`.

An archive holds exactly these files. A symbolic link, or a path
holding a newline or a tab, is an error. Empty directories are not
listed, as in git. A `.marigoldignore` file may replace the fixed list
later.

## With standard tools

Run in an application's root, this prints the same manifest and digest
Marigold computes:

```sh
find . \( -name .git -o -name .hg -o -name .svn -o -name __pycache__ \
          -o -name .venv -o -name venv -o -name node_modules \
          -o -name .mypy_cache -o -name .pytest_cache -o -name .ruff_cache \
          -o -name .DS_Store -o -name dist -o -name build -o -name .env \
          -o -name '*.pyc' -o -name '*.pyo' -o -name '*.tar.gz' \
          -o -name '*.tgz' -o -name '*.marigold' \) -prune \
       -o -type f -print \
  | sed 's#^\./##' | LC_ALL=C sort \
  | while IFS= read -r f; do
      mode=100644
      [ -n "$(find "$f" -perm -u=x)" ] && mode=100755
      printf '%s %s  %s\n' "$mode" "$(sha256sum < "$f" | cut -d' ' -f1)" "$f"
    done > ../app.manifest

sha256sum ../app.manifest                         # the digest
cut -d' ' -f2- ../app.manifest | sha256sum -c     # check every file
```

The last line works because a manifest line without its mode is a
`sha256sum` line.

To compare two versions by hand, compute both manifests and
`diff` them: the changed lines are the changed files.
