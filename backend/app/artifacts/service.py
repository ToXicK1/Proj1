"""Versioned artifacts. Every stage output is a new immutable version; nothing is edited in place."""

import hashlib
import json
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.artifacts.models import Artifact, ArtifactVersion
from app.core.db import uuid7


def content_sha256(content: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def create_version(
    db: Session,
    *,
    project_id: uuid.UUID,
    stage_execution_id: uuid.UUID,
    kind: str,
    content: dict[str, Any],
    author_user_id: uuid.UUID | None = None,
) -> ArtifactVersion:
    """Append a version to the stage's artifact (created on first use). Does not commit."""
    artifact = db.execute(
        select(Artifact).where(Artifact.stage_execution_id == stage_execution_id).with_for_update()
    ).scalar_one_or_none()
    if artifact is None:
        artifact = Artifact(id=uuid7(), project_id=project_id, stage_execution_id=stage_execution_id, kind=kind)
        db.add(artifact)
        db.flush()
    last = db.execute(
        select(func.max(ArtifactVersion.version_number)).where(ArtifactVersion.artifact_id == artifact.id)
    ).scalar_one()
    version = ArtifactVersion(
        id=uuid7(),
        artifact_id=artifact.id,
        version_number=(last or 0) + 1,
        content_json=content,
        content_sha256=content_sha256(content),
        author_type="human" if author_user_id else "system",
        author_user_id=author_user_id,
    )
    db.add(version)
    db.flush()
    artifact.current_version_id = version.id
    return version


def current_version(db: Session, stage_execution_id: uuid.UUID) -> tuple[Artifact, ArtifactVersion] | None:
    artifact = db.execute(select(Artifact).where(Artifact.stage_execution_id == stage_execution_id)).scalar_one_or_none()
    if artifact is None or artifact.current_version_id is None:
        return None
    version = db.get(ArtifactVersion, artifact.current_version_id)
    return artifact, version
