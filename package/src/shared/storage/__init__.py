"""Binary object storage.

Callers address objects by key, a relative path such as
"outputs/txt2img/<id>_image.png". The backend, its root or bucket, and
its credentials come from the environment and never appear in this
module's interface.

    MARIGOLD_STORAGE           fs (default) | s3
    MARIGOLD_STORAGE_ROOT      fs: directory keys resolve under (default /data)
    MARIGOLD_STORAGE_BUCKET    s3: bucket name; must already exist
    MARIGOLD_STORAGE_ENDPOINT  s3: endpoint URL; unset means AWS S3

s3 credentials and region come from boto3's own sources: AWS_ACCESS_KEY_ID,
AWS_SECRET_ACCESS_KEY, AWS_DEFAULT_REGION, a credentials file, or an
instance role.
"""

import os
from functools import lru_cache

from shared.storage.base import (
    InvalidKey, ObjectNotFound, ObjectStat, SavedObject, Storage, StorageError,
)

__all__ = [
    "get_storage", "Storage", "SavedObject", "ObjectStat",
    "StorageError", "ObjectNotFound", "InvalidKey",
]


@lru_cache(maxsize=1)
def get_storage() -> Storage:
    backend = os.environ.get("MARIGOLD_STORAGE", "fs")

    if backend == "fs":
        from shared.storage.fs import FilesystemStorage
        return FilesystemStorage(os.environ.get("MARIGOLD_STORAGE_ROOT", "/data"))

    if backend == "s3":
        from shared.storage.s3 import S3Storage   # boto3 is imported only here
        return S3Storage(
            bucket=os.environ.get("MARIGOLD_STORAGE_BUCKET", ""),
            endpoint_url=os.environ.get("MARIGOLD_STORAGE_ENDPOINT") or None,
        )

    raise StorageError(f"unknown MARIGOLD_STORAGE backend: {backend}")
