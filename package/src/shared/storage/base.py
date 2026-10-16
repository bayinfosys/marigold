"""Types, errors and key rules shared by every storage backend."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
from typing import BinaryIO, Iterator, Protocol, Union

CHUNK_SIZE = 1024 * 1024

Data = Union[bytes, BinaryIO, Iterator[bytes]]


class StorageError(Exception):
    """Base class for every storage failure."""


class ObjectNotFound(StorageError):
    pass


class InvalidKey(StorageError):
    pass


@dataclass(frozen=True)
class SavedObject:
    key: str
    size: int
    sha256: str
    mimetype: str


@dataclass(frozen=True)
class ObjectStat:
    key: str
    size: int
    modified: datetime


def validate_key(key: str) -> str:
    """Keys are relative POSIX paths with no '..' segments. The same rules
    apply to every backend, so a key valid on one is valid on all."""
    if not key or "\\" in key:
        raise InvalidKey(key)

    path = PurePosixPath(key)

    if path.is_absolute() or ".." in path.parts:
        raise InvalidKey(key)

    return str(path)


def iter_chunks(data: Data) -> Iterator[bytes]:
    if isinstance(data, bytes):
        yield data
    elif hasattr(data, "read"):
        while chunk := data.read(CHUNK_SIZE):
            yield chunk
    else:
        yield from data


class Storage(Protocol):
    def save(self, key: str, data: Data, mimetype: str) -> SavedObject: ...
    def read(self, key: str) -> bytes: ...
    def stream(self, key: str) -> Iterator[bytes]: ...
    def exists(self, key: str) -> bool: ...
    def size(self, key: str) -> int: ...
    def stat(self, key: str) -> ObjectStat: ...
    def delete(self, key: str) -> None: ...
    def list(self, prefix: str) -> Iterator[str]: ...
