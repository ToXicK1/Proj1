"""Codebase Explorer records: what the deterministic analysis found in a project repository, per branch.

`code_indexes` holds the state of each branch's index (not indexed, indexing, up to date, partly indexed, failed) and
the commit it describes. `repository_files` holds one row per file path and branch (never two for the same path), with
the blob hash as the content hash, so unchanged files are not parsed again. `file_dependencies` holds each import or
reference found, how it was found and how far it resolved; a target file is set only when the import resolved to a file
of the repository. No source code is stored here.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

INDEX_STATUS = ("indexing", "up_to_date", "partial", "failed")
RESOLUTION = ("confirmed", "partial", "unresolved", "external", "dynamic")
RELATIONSHIP = ("imports", "re_exports", "requires", "dynamic_import", "tests")


class CodeIndex(Base):
    __tablename__ = "code_indexes"
    __table_args__ = (UniqueConstraint("repository_id", "branch", name="uq_code_indexes_repo_branch"),
                      CheckConstraint(f"status in {INDEX_STATUS}", name="status_valid"))

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("projects.id"), nullable=False, index=True)
    repository_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("repositories.id"), nullable=False)
    branch: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="indexing")
    commit: Mapped[str] = mapped_column(String(40), nullable=False, default="")  # the commit the records describe
    requested_commit: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    counts: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)  # files, parsed, reused, edges, ...
    failure: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RepositoryFile(Base):
    __tablename__ = "repository_files"
    __table_args__ = (UniqueConstraint("repository_id", "branch", "relative_path", name="uq_repository_files_repo_branch_path"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("projects.id"), nullable=False)
    repository_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("repositories.id"), nullable=False)
    branch: Mapped[str] = mapped_column(String(100), nullable=False)
    relative_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    extension: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    file_type: Mapped[str] = mapped_column(String(16), nullable=False)  # source, test, config, docs, entry, other
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content_hash: Mapped[str] = mapped_column(String(40), nullable=False)  # the git blob id
    analysis_status: Mapped[str] = mapped_column(String(24), nullable=False, default="not_parsed")
    analysis_error: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    imports: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)  # as written, to re-resolve
    last_indexed_commit: Mapped[str] = mapped_column(String(40), nullable=False)
    indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class FileDependency(Base):
    __tablename__ = "file_dependencies"
    __table_args__ = (
        CheckConstraint(f"resolution_status in {RESOLUTION}", name="resolution_valid"),
        CheckConstraint(f"relationship_type in {RELATIONSHIP}", name="relationship_valid"),
        CheckConstraint("target_file_id is not null or resolution_status <> 'confirmed'", name="confirmed_has_target"),
        Index("ix_file_dependencies_source", "source_file_id"),
        Index("ix_file_dependencies_target", "target_file_id"),
        Index("ix_file_dependencies_repo_branch", "repository_id", "branch"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    repository_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("repositories.id"), nullable=False)
    branch: Mapped[str] = mapped_column(String(100), nullable=False)
    source_file_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("repository_files.id", ondelete="CASCADE"),
                                                      nullable=False)
    target_file_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("repository_files.id",
                                                                              ondelete="CASCADE"), nullable=True)
    target_spec: Mapped[str] = mapped_column(String(300), nullable=False, default="")  # as written in the source
    relationship_type: Mapped[str] = mapped_column(String(16), nullable=False)
    discovery_method: Mapped[str] = mapped_column(String(24), nullable=False)  # python_ast, typescript_parser, naming
    resolution_status: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    line: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_indexed_commit: Mapped[str] = mapped_column(String(40), nullable=False)
