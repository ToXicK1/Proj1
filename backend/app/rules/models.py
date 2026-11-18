import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

SCOPES = ("organization", "team", "project", "profile", "stage", "agent")
KINDS = ("mandatory", "prohibited", "coding_standard", "security_policy", "documentation",
         "architecture_constraint", "testing", "industry", "convention")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


class Team(Base):
    __tablename__ = "teams"
    __table_args__ = (UniqueConstraint("organization_id", "key", name="uq_teams_org_key"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ProjectTeam(Base):
    __tablename__ = "project_teams"

    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("projects.id"), primary_key=True)
    team_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("teams.id"), primary_key=True)


class Rule(Base):
    __tablename__ = "rules"
    __table_args__ = (
        UniqueConstraint("organization_id", "scope_type", "scope_key", "key", name="uq_rules_scope_key"),
        CheckConstraint(f"scope_type in ({_in(SCOPES)})", name="scope_valid"),
        CheckConstraint(f"kind in ({_in(KINDS)})", name="kind_valid"),
        CheckConstraint("status in ('active','retired')", name="status_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False)
    scope_key: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class RuleVersion(Base):
    """Immutable rule text and its authorship. The versions of a rule are its change history."""

    __tablename__ = "rule_versions"
    __table_args__ = (UniqueConstraint("rule_id", "version", name="uq_rule_versions_rule_version"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    rule_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("rules.id"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    author_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    change_note: Mapped[str] = mapped_column(String(300), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ChangeProposal(Base):
    """A proposed rule or hook. It has no effect until an authorized person approves it."""

    __tablename__ = "change_proposals"
    __table_args__ = (
        CheckConstraint("target in ('rule','hook')", name="target_valid"),
        CheckConstraint("proposer_type in ('human','ai_agent')", name="proposer_type_valid"),
        CheckConstraint("status in ('pending','approved','rejected')", name="status_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), nullable=False, index=True)
    target: Mapped[str] = mapped_column(String(8), nullable=False)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    conflicts: Mapped[list] = mapped_column(JSONB, nullable=False)
    proposer_type: Mapped[str] = mapped_column(String(16), nullable=False)
    proposer_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    source_change_request_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("change_requests.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    decided_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    decision_note: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
