"""Application manifests: what an application is, file by file.

A manifest lists every file in an application, one line each, sorted:

    <mode> <sha256>  <path>

    100644 91de...4c  marigold.toml
    100755 a07b...12  run.sh

mode is git's: 100755 when the owner may execute the file, 100644
otherwise. sha256 is of the file's bytes as they are, with no line-ending
conversion. path is relative to the application root, '/'-separated,
UTF-8, and lines are sorted by the path's bytes. Every line ends in a
newline.

The application's digest is the sha256 of the manifest text. Equal
digests mean equal files, whatever the archive bytes or the version
label. The manifest is never stored or sent: the build, the registry
build and the installer each compute it from the files in front of
them, and the registry's index carries only the digest.

Which files: every regular file under the root, hidden files included,
as git does, except the names and suffixes below. A symbolic link, or a
path holding a newline or a tab, is an error.

The same manifest from standard tools, run in the application root
(docs/manifests.md has the exclusions written out in full):

    find . <exclusions> -type f -print | sed 's#^\\./##' | LC_ALL=C sort |
    while IFS= read -r f; do
        mode=100644; [ -n "$(find "$f" -perm -u=x)" ] && mode=100755
        printf '%s %s  %s\\n' "$mode" "$(sha256sum < "$f" | cut -d' ' -f1)" "$f"
    done > ../app.manifest
    sha256sum ../app.manifest                    # the digest
    cut -d' ' -f2- ../app.manifest | sha256sum -c   # check every file
"""

import hashlib
import os

from pathlib import Path

ARCHIVE_SUFFIXES = (".tar.gz", ".tgz", ".marigold")

# Excluded wherever they appear in a path. Replaced by a .marigoldignore
# file when one is needed; until then, this list is the rule.
EXCLUDED_NAMES = frozenset({
    ".git", ".hg", ".svn", "__pycache__", ".venv", "venv", "node_modules",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".DS_Store", "dist", "build",
    ".env",
})
EXCLUDED_SUFFIXES = (".pyc", ".pyo") + ARCHIVE_SUFFIXES

MODE_FILE = "100644"
MODE_EXECUTABLE = "100755"

SHORT = 12


def short(digest: str) -> str:
    """A digest as shown to people: the first 12 hex characters."""
    return digest[:SHORT]


def _excluded(name: str) -> bool:
    return name in EXCLUDED_NAMES or name.endswith(EXCLUDED_SUFFIXES)


def application_files(root: Path) -> list[Path]:
    """The files an application is made of, sorted by path bytes.

    The archive holds exactly these files, and the manifest lists them.
    """
    root = root.resolve()
    found: list[tuple[bytes, Path]] = []

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        kept = []

        for name in dirnames:
            path = current / name
            if _excluded(name):
                continue
            if path.is_symlink():
                raise ValueError(f"{path}: symbolic links are not allowed in an application")
            kept.append(name)

        dirnames[:] = kept

        for name in filenames:
            path = current / name
            if _excluded(name):
                continue
            if path.is_symlink():
                raise ValueError(f"{path}: symbolic links are not allowed in an application")
            if not path.is_file():
                continue

            relative = path.relative_to(root).as_posix()
            if "\n" in relative or "\t" in relative:
                raise ValueError(f"{relative!r}: a path may not hold a newline or a tab")

            found.append((relative.encode("utf-8"), path))

    return [path for _, path in sorted(found)]


def file_mode(executable: bool) -> str:
    return MODE_EXECUTABLE if executable else MODE_FILE


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)

    return digest.hexdigest()


def format_line(mode: str, sha256: str, path: str) -> str:
    return f"{mode} {sha256}  {path}\n"


def manifest_text(root: Path) -> str:
    """The manifest of an application directory."""
    root = root.resolve()
    lines = []

    for path in application_files(root):
        executable = bool(path.stat().st_mode & 0o100)
        lines.append(format_line(file_mode(executable), file_sha256(path), path.relative_to(root).as_posix()))

    return "".join(lines)


def text_digest(text: str) -> str:
    """The digest of a manifest: sha256 of its text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def application_manifest(root: Path) -> tuple[str, str]:
    """(manifest text, digest) for an application directory."""
    text = manifest_text(root)
    return text, text_digest(text)


def parse(text: str) -> dict[str, tuple[str, str]]:
    """path -> (mode, sha256)."""
    entries = {}

    for line in text.splitlines():
        mode, sha256, path = line.split(" ", 2)
        entries[path.removeprefix(" ")] = (mode, sha256)

    return entries


def compare(old: str, new: str) -> dict[str, list[str]]:
    """Paths added, removed and changed between two manifests."""
    a, b = parse(old), parse(new)

    return {
        "added": sorted(set(b) - set(a)),
        "removed": sorted(set(a) - set(b)),
        "changed": sorted(path for path in set(a) & set(b) if a[path] != b[path]),
    }
