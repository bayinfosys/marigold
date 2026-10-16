"""Filesystem storage: keys resolve under one root directory."""

import hashlib
import os
import tempfile

from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from shared.storage.base import (
    CHUNK_SIZE, Data, ObjectNotFound, ObjectStat, SavedObject,
    iter_chunks, validate_key,
)


class FilesystemStorage:
    def __init__(self, root: str):
        self._root = Path(root)

    def _path(self, key: str) -> Path:
        return self._root / validate_key(key)

    def save(self, key: str, data: Data, mimetype: str) -> SavedObject:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        digest, size = hashlib.sha256(), 0
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")

        try:
            with os.fdopen(fd, "wb") as f:
                for chunk in iter_chunks(data):
                    f.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
            os.replace(tmp, path)          # atomic on one filesystem
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

        return SavedObject(key=key, size=size, sha256=digest.hexdigest(), mimetype=mimetype)

    def stream(self, key: str) -> Iterator[bytes]:
        try:
            f = open(self._path(key), "rb")
        except FileNotFoundError:
            raise ObjectNotFound(key) from None

        with f:
            while chunk := f.read(CHUNK_SIZE):
                yield chunk

    def read(self, key: str) -> bytes:
        return b"".join(self.stream(key))

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def stat(self, key: str) -> ObjectStat:
        try:
            st = self._path(key).stat()
        except FileNotFoundError:
            raise ObjectNotFound(key) from None

        return ObjectStat(
            key=key, size=st.st_size,
            modified=datetime.fromtimestamp(st.st_mtime, tz=timezone.utc),
        )

    def size(self, key: str) -> int:
        return self.stat(key).size

    def delete(self, key: str) -> None:
        try:
            self._path(key).unlink()
        except FileNotFoundError:
            raise ObjectNotFound(key) from None

    def list(self, prefix: str) -> Iterator[str]:
        base = self._root / validate_key(prefix) if prefix else self._root

        if not base.exists():
            return

        for p in base.rglob("*"):
            if p.is_file() and not p.name.startswith(".tmp-"):
                yield p.relative_to(self._root).as_posix()
