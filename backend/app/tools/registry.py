"""The tool registry in the database (Phase 1c).

`tool_registry` mirrors the reviewed definitions (app/tools/definitions.py) and adds run-time state: whether an
administrator has enabled each tool, and its health. Every definition version is kept in `tool_registry_versions`, so
what a tool was at any time stays on record. Sync runs at start-up; nothing else adds or changes definitions.

Health: in-process tools are healthy while the API serves; executor tools are healthy while the executor reports in
(it touches its tools every few seconds; silence for two minutes reads as unavailable).
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Uuid, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.db import Base
from app.tools.definitions import DEFINITIONS

STALE_AFTER = timedelta(minutes=2)


class ToolRegistryEntry(Base):
    __tablename__ = "tool_registry"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    definition: Mapped[dict] = mapped_column(JSONB, nullable=False)
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    health: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")  # unknown, ok, unavailable
    health_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ToolRegistryVersion(Base):
    __tablename__ = "tool_registry_versions"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    definition: Mapped[dict] = mapped_column(JSONB, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


def sync(db: Session) -> list[str]:
    """Brings the registry up to the reviewed definitions. Returns the keys added or changed. The caller commits."""
    changed = []
    existing = {e.key: e for e in db.execute(select(ToolRegistryEntry)).scalars()}
    for key, definition in DEFINITIONS.items():
        record = definition.record()
        entry = existing.get(key)
        if entry is not None and entry.version == definition.version and entry.definition == record:
            continue
        if entry is not None and entry.version == definition.version:
            raise RuntimeError(f"tool {key} changed without a new version")  # every change must be versioned
        if db.get(ToolRegistryVersion, (key, definition.version)) is None:
            db.add(ToolRegistryVersion(key=key, version=definition.version, definition=record))
        if entry is None:
            db.add(ToolRegistryEntry(key=key, version=definition.version, definition=record, enabled=True,
                                     health="ok" if definition.environment == "in_process" else "unknown"))
        else:
            entry.version, entry.definition, entry.updated_at = definition.version, record, datetime.now(UTC)
        changed.append(key)
    return changed


def disabled(db: Session) -> frozenset[str]:
    return frozenset(db.execute(select(ToolRegistryEntry.key).where(ToolRegistryEntry.enabled.is_(False))).scalars())


def report_executor_alive(db: Session) -> None:
    """The executor's heartbeat: its tools are reachable. The caller commits."""
    now = datetime.now(UTC)
    for entry in db.execute(select(ToolRegistryEntry)).scalars():
        if entry.definition.get("environment") == "executor":
            entry.health, entry.health_checked_at = "ok", now


def health_of(entry: ToolRegistryEntry, now: datetime | None = None) -> str:
    if entry.definition.get("environment") != "executor":
        return "ok"
    now = now or datetime.now(UTC)
    if entry.health_checked_at is None or now - entry.health_checked_at > STALE_AFTER:
        return "unavailable"
    return entry.health


def entry_out(entry: ToolRegistryEntry) -> dict[str, Any]:
    from app.agents.tools import GRANTABLE_THIS_MILESTONE, PermissionClass

    definition = entry.definition
    return {**definition, "enabled": entry.enabled, "health": health_of(entry),
            "health_checked_at": entry.health_checked_at.isoformat() if entry.health_checked_at else None,
            "grantable": PermissionClass(definition["permission_class"]) in GRANTABLE_THIS_MILESTONE
            and bool(definition["departments"]) and entry.enabled}
