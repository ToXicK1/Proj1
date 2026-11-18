import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AuditChain(Base):
    """One row per hash chain (the platform chain or one per organization). Locked to serialize appends."""

    __tablename__ = "audit_chains"

    chain_key: Mapped[str] = mapped_column(String(120), primary_key=True)
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    head_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class AuditEvent(Base):
    """Append-only event. UPDATE and DELETE are blocked by a database trigger (migration 0001)."""

    __tablename__ = "audit_events"
    __table_args__ = (
        UniqueConstraint("chain_key", "seq", name="uq_audit_events_chain_seq"),
        CheckConstraint(
            "actor_type in ('human','ai_agent','system','hook','provider')",
            name="actor_type_valid",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    chain_key: Mapped[str] = mapped_column(String(120), ForeignKey("audit_chains.chain_key"), nullable=False)
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    hash: Mapped[str] = mapped_column(String(64), nullable=False)
