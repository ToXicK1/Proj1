"""What the platform keeps in object storage (RD-5). The bytes live in the bucket; this table is the record."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class StoredObject(Base):
    __tablename__ = "stored_objects"
    __table_args__ = (CheckConstraint("size_bytes >= 0", name="size_valid"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    key: Mapped[str] = mapped_column(String(400), nullable=False, unique=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), nullable=False,
                                                       index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("projects.id"), nullable=True, index=True)
    purpose: Mapped[str] = mapped_column(String(64), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
