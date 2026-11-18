import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Skill(Base):
    """A reusable instruction set. Behaviour lives in immutable skill versions."""

    __tablename__ = "skills"
    __table_args__ = (UniqueConstraint("organization_id", "key", name="uq_skills_org_key"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SkillVersion(Base):
    """Immutable: UPDATE and DELETE are blocked by trigger. An agent version pins one of these."""

    __tablename__ = "skill_versions"
    __table_args__ = (UniqueConstraint("skill_id", "version", name="uq_skill_versions_skill_version"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    skill_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("skills.id"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    instructions: Mapped[str] = mapped_column(Text, nullable=False)
    required_tools: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    compatible_profiles: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # Stage keys this version may run in. Empty means any stage. Checked when a stage runs.
    compatible_stages: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # Exact versions this version builds on: [{"key": ..., "version": n}], fixed at creation.
    dependencies: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
