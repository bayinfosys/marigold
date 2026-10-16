"""S3-compatible storage: AWS S3, SeaweedFS, Garage, RustFS or any other
service that speaks the S3 API.

boto3 is imported here and nowhere else, so an fs installation never
loads it. The bucket must exist; Marigold does not create it.
"""

import hashlib

from typing import Iterator

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.exceptions import ClientError

from shared.storage.base import (
    CHUNK_SIZE, Data, ObjectNotFound, ObjectStat, SavedObject, StorageError,
    iter_chunks, validate_key,
)

_NOT_FOUND = {"404", "NoSuchKey", "NotFound"}


def _is_not_found(e: ClientError) -> bool:
    return e.response.get("Error", {}).get("Code") in _NOT_FOUND


class _HashingReader:
    """A file-like reader over chunks that hashes and counts what it yields.

    Lets an upload compute sha256 and size in the same pass, without
    holding the whole object in memory.
    """

    def __init__(self, chunks: Iterator[bytes]):
        self._chunks = chunks
        self._buffer = b""
        self.digest = hashlib.sha256()
        self.size = 0

    def read(self, n: int = -1) -> bytes:
        while n < 0 or len(self._buffer) < n:
            try:
                self._buffer += next(self._chunks)
            except StopIteration:
                break

        if n < 0:
            out, self._buffer = self._buffer, b""
        else:
            out, self._buffer = self._buffer[:n], self._buffer[n:]

        self.digest.update(out)
        self.size += len(out)
        return out


class S3Storage:
    def __init__(self, bucket: str, endpoint_url: str | None = None):
        if not bucket:
            raise StorageError("MARIGOLD_STORAGE_BUCKET is required for the s3 backend")

        self._bucket = bucket
        self._client = boto3.client("s3", endpoint_url=endpoint_url)
        # Sequential reads, so the hash sees the bytes in order.
        self._transfer = TransferConfig(use_threads=False)

    def save(self, key: str, data: Data, mimetype: str) -> SavedObject:
        key = validate_key(key)
        reader = _HashingReader(iter_chunks(data))

        try:
            self._client.upload_fileobj(
                reader, self._bucket, key,
                ExtraArgs={"ContentType": mimetype},
                Config=self._transfer,
            )
        except ClientError as e:
            raise StorageError(f"cannot write {key}: {e}") from e

        return SavedObject(
            key=key, size=reader.size, sha256=reader.digest.hexdigest(), mimetype=mimetype,
        )

    def stream(self, key: str) -> Iterator[bytes]:
        key = validate_key(key)

        try:
            obj = self._client.get_object(Bucket=self._bucket, Key=key)
        except ClientError as e:
            if _is_not_found(e):
                raise ObjectNotFound(key) from None
            raise StorageError(f"cannot read {key}: {e}") from e

        body = obj["Body"]

        try:
            yield from body.iter_chunks(CHUNK_SIZE)
        finally:
            body.close()

    def read(self, key: str) -> bytes:
        return b"".join(self.stream(key))

    def stat(self, key: str) -> ObjectStat:
        key = validate_key(key)

        try:
            head = self._client.head_object(Bucket=self._bucket, Key=key)
        except ClientError as e:
            if _is_not_found(e):
                raise ObjectNotFound(key) from None
            raise StorageError(f"cannot stat {key}: {e}") from e

        return ObjectStat(key=key, size=head["ContentLength"], modified=head["LastModified"])

    def exists(self, key: str) -> bool:
        try:
            self.stat(key)
            return True
        except ObjectNotFound:
            return False

    def size(self, key: str) -> int:
        return self.stat(key).size

    def delete(self, key: str) -> None:
        self.stat(key)          # raises ObjectNotFound, matching the fs backend
        self._client.delete_object(Bucket=self._bucket, Key=validate_key(key))

    def list(self, prefix: str) -> Iterator[str]:
        if prefix:
            validate_key(prefix)

        paginator = self._client.get_paginator("list_objects_v2")

        for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix or ""):
            for obj in page.get("Contents", []):
                yield obj["Key"]
