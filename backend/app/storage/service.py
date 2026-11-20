"""Object storage for files and large artifacts. Keys are scoped by organization and project.

Every read checks the bytes against the SHA-256 recorded when they were written, so a changed or corrupted
object is refused rather than served.
"""

import hashlib
import re
import uuid
from functools import lru_cache
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.db import uuid7
from app.storage.models import StoredObject
from app.storage.s3 import S3Client, StorageError

_PURPOSE = re.compile(r"^[a-z][a-z0-9_-]{1,40}$")
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")


class IntegrityError(Exception):
    """The stored bytes no longer match the recorded hash."""


@lru_cache(maxsize=4)
def _client(endpoint: str, access_key: str, secret_key: str, region: str) -> S3Client:
    return S3Client(endpoint, access_key, secret_key, region)


def client(settings: Settings, transport: Any = None) -> S3Client:
    if not settings.storage_enabled:
        raise RuntimeError("object storage is not configured")
    if transport is not None:  # tests replace the network
        return S3Client(settings.storage_endpoint, settings.storage_access_key, settings.storage_secret_key,
                        settings.storage_region, transport=transport)
    return _client(settings.storage_endpoint, settings.storage_access_key, settings.storage_secret_key,
                   settings.storage_region)


def object_key(organization_id: uuid.UUID, project_id: uuid.UUID | None, purpose: str, name: str) -> str:
    if not _PURPOSE.fullmatch(purpose) or not _NAME.fullmatch(name):
        raise ValueError("unsafe object name")
    project = f"projects/{project_id}" if project_id else "shared"
    return f"orgs/{organization_id}/{project}/{purpose}/{name}"


def find(db: Session, key: str) -> StoredObject | None:
    return db.execute(select(StoredObject).where(StoredObject.key == key)).scalar_one_or_none()


def save(db: Session, settings: Settings, *, organization_id: uuid.UUID, project_id: uuid.UUID | None,
         purpose: str, name: str, data: bytes, content_type: str, transport: Any = None) -> StoredObject:
    """Writes the bytes, then records them in the caller's transaction. Writing the same key again is a no-op."""
    key = object_key(organization_id, project_id, purpose, name)
    existing = find(db, key)
    if existing is not None:
        return existing
    client(settings, transport).put(settings.storage_bucket, key, data, content_type)
    row = StoredObject(id=uuid7(), key=key, organization_id=organization_id, project_id=project_id, purpose=purpose,
                       content_type=content_type, size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
    db.add(row)
    db.flush()
    return row


def load(settings: Settings, row: StoredObject, transport: Any = None) -> bytes:
    data = client(settings, transport).get(settings.storage_bucket, row.key)
    if hashlib.sha256(data).hexdigest() != row.sha256 or len(data) != row.size_bytes:
        raise IntegrityError(row.key)
    return data


def ensure_bucket(settings: Settings, transport: Any = None) -> bool:
    return client(settings, transport).ensure_bucket(settings.storage_bucket)


def ready(settings: Settings, transport: Any = None) -> bool:
    """True when the bucket answers. Used by the readiness check."""
    try:
        return client(settings, transport).bucket_exists(settings.storage_bucket)
    except (httpx.HTTPError, StorageError, RuntimeError):
        return False
