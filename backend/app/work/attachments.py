"""Files attached to work records (P2: a client meeting's documents and references).

The bytes go to object storage under a random name; the record row keeps the original filename for display only.
Only the record's department can attach; anyone who may read the record may download. Only safe, common document
and image types are accepted (no HTML, SVG or scripts), up to MAX_BYTES, and downloads are always served as
attachments with sniffing disabled, so a file can never run in the platform's pages.
"""

import re
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import User
from app.core.config import Settings
from app.core.db import uuid7
from app.core.errors import AppError, not_found
from app.storage import service as storage
from app.storage.models import StoredObject
from app.work import service as work
from app.work.models import WorkAttachment, WorkItem

MAX_BYTES = 10 * 1024 * 1024
ALLOWED: dict[str, str] = {
    "application/pdf": "pdf", "image/png": "png", "image/jpeg": "jpg", "text/plain": "txt", "text/markdown": "md",
    "text/csv": "csv", "application/msword": "doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
}
_UNSAFE = re.compile(r"[^A-Za-z0-9 ._()-]+")


def _clean_name(filename: str) -> str:
    name = _UNSAFE.sub("_", filename.replace("\\", "/").rsplit("/", 1)[-1]).strip(" .") or "file"
    return name[:200]


def _out(db: Session, a: WorkAttachment) -> dict[str, Any]:
    names = work._names(db, {a.uploaded_by})
    return {"id": str(a.id), "filename": a.filename, "content_type": a.content_type, "size_bytes": a.size_bytes,
            "uploaded_by": names.get(a.uploaded_by), "created_at": a.created_at.isoformat()}


def _readable_item(db: Session, user: User, project_id: uuid.UUID, item_id: uuid.UUID) -> tuple[Any, WorkItem]:
    project, scope = work._scope(db, user, project_id)
    item = work._item(db, project_id, item_id)
    if not work.reads_all(scope, item.department) and item.id not in work.approved_versions(db, project.id):
        raise not_found()
    return project, item


def attach(db: Session, settings: Settings, user: User, project_id: uuid.UUID, item_id: uuid.UUID, *,
           filename: str, content_type: str, data: bytes, transport: Any = None) -> dict[str, Any]:
    project, _ = work._scope(db, user, project_id)
    item = work._item(db, project_id, item_id)
    work._require_editor(db, user, project, item.department)
    kind = content_type.split(";", 1)[0].strip().lower()
    if kind not in ALLOWED:
        raise AppError(415, "file_type_not_allowed", "Attach a PDF, image, text, CSV or Office document")
    if not data:
        raise AppError(422, "empty_file", "The file is empty")
    if len(data) > MAX_BYTES:
        raise AppError(413, "file_too_large", "Files can be at most 10 MB")
    if not settings.storage_enabled:
        raise AppError(503, "storage_unavailable", "File storage is not configured")
    stored = storage.save(db, settings, organization_id=project.organization_id, project_id=project.id,
                          purpose="attachments", name=f"{uuid.uuid4().hex}.{ALLOWED[kind]}", data=data,
                          content_type=kind, transport=transport)
    row = WorkAttachment(id=uuid7(), project_id=project.id, item_id=item.id, stored_object_id=stored.id,
                         filename=_clean_name(filename), content_type=kind, size_bytes=len(data), uploaded_by=user.id)
    db.add(row)
    work._audit(db, project, "work.attachment_added", user, {"item": str(item.id), "attachment": str(row.id),
                                                             "sha256": stored.sha256, "bytes": len(data)})
    db.commit()
    return _out(db, row)


def list_for(db: Session, user: User, project_id: uuid.UUID, item_id: uuid.UUID) -> list[dict[str, Any]]:
    _, item = _readable_item(db, user, project_id, item_id)
    rows = db.execute(select(WorkAttachment).where(WorkAttachment.item_id == item.id)
                      .order_by(WorkAttachment.created_at)).scalars()
    return [_out(db, a) for a in rows]


def download(db: Session, settings: Settings, user: User, project_id: uuid.UUID, attachment_id: uuid.UUID,
             transport: Any = None) -> tuple[WorkAttachment, bytes]:
    row = db.get(WorkAttachment, attachment_id)
    if row is None or row.project_id != project_id:
        raise not_found()
    _readable_item(db, user, project_id, row.item_id)
    stored = db.get(StoredObject, row.stored_object_id)
    try:
        return row, storage.load(settings, stored, transport)
    except storage.IntegrityError as exc:
        raise AppError(409, "file_changed", "This file no longer matches what was stored") from exc
