"""The tool registry over HTTP (Phase 1c): anyone in an organization reads it; administrators enable or disable
tools (audited). Definitions cannot be created or changed here."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.audit.service import append_event, org_chain
from app.auth.deps import CsrfCaller, CurrentCaller, DbSession
from app.core.errors import not_found
from app.organizations.service import membership_for, require_org_admin
from app.tools.registry import ToolRegistryEntry, entry_out

router = APIRouter(prefix="/api/v1/orgs/{organization_id}/tool-registry", tags=["tools"])


class EnabledIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


@router.get("")
def registry(organization_id: uuid.UUID, caller: CurrentCaller, db: DbSession) -> dict:
    if membership_for(db, caller.user.id, organization_id) is None:
        raise not_found()
    rows = db.execute(select(ToolRegistryEntry).order_by(ToolRegistryEntry.key)).scalars()
    return {"items": [entry_out(e) for e in rows]}


@router.put("/{key}")
def set_enabled(organization_id: uuid.UUID, key: str, body: EnabledIn, caller: CsrfCaller, db: DbSession) -> dict:
    require_org_admin(db, caller.user.id, organization_id)
    entry = db.get(ToolRegistryEntry, key)
    if entry is None:
        raise not_found()
    previous, entry.enabled = entry.enabled, body.enabled
    entry.updated_by_user_id, entry.updated_at = caller.user.id, datetime.now(UTC)
    append_event(db, chain_key=org_chain(organization_id), event_type="tool_registry.changed", actor_type="human",
                 actor_id=str(caller.user.id), organization_id=organization_id,
                 payload={"tool": key, "version": entry.version, "enabled": body.enabled, "previous": previous})
    db.commit()
    return entry_out(entry)
