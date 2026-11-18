"""Tamper-evident audit writer and verifier.

Each event stores prev_hash and hash = SHA-256(prev_hash + canonical JSON of the event).
Appends lock the chain row, so each chain has one writer at a time. Events are written in the
same transaction as the change they describe: the caller commits both or neither.
"""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.audit.models import AuditChain, AuditEvent
from app.core.security import sha256_hex

GENESIS_HASH = "0" * 64
PLATFORM_CHAIN = "platform"


def org_chain(organization_id: uuid.UUID) -> str:
    return f"org:{organization_id}"


def _canonical(
    *,
    chain_key: str,
    seq: int,
    event_type: str,
    actor_type: str,
    actor_id: str | None,
    organization_id: uuid.UUID | None,
    project_id: uuid.UUID | None,
    payload: dict[str, Any],
    occurred_at: datetime,
) -> str:
    body = {
        "chain_key": chain_key,
        "seq": seq,
        "event_type": event_type,
        "actor_type": actor_type,
        "actor_id": actor_id,
        "organization_id": str(organization_id) if organization_id else None,
        "project_id": str(project_id) if project_id else None,
        "payload": payload,
        "occurred_at": occurred_at.astimezone(UTC).isoformat(timespec="microseconds"),
    }
    return json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)


def compute_hash(prev_hash: str, **fields: Any) -> str:
    return sha256_hex(prev_hash + _canonical(**fields))


def append_event(
    db: Session,
    *,
    chain_key: str,
    event_type: str,
    actor_type: str,
    actor_id: str | None = None,
    organization_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    payload: dict[str, Any] | None = None,
) -> AuditEvent:
    """Append one event to a chain. Does not commit; the caller's transaction owns that."""
    db.execute(
        insert(AuditChain)
        .values(chain_key=chain_key, seq=0, head_hash=GENESIS_HASH)
        .on_conflict_do_nothing(index_elements=["chain_key"])
    )
    chain = db.execute(
        select(AuditChain).where(AuditChain.chain_key == chain_key).with_for_update()
    ).scalar_one()

    seq = chain.seq + 1
    prev_hash = chain.head_hash
    occurred_at = datetime.now(UTC)
    body = payload or {}
    digest = compute_hash(
        prev_hash,
        chain_key=chain_key,
        seq=seq,
        event_type=event_type,
        actor_type=actor_type,
        actor_id=actor_id,
        organization_id=organization_id,
        project_id=project_id,
        payload=body,
        occurred_at=occurred_at,
    )
    event = AuditEvent(
        chain_key=chain_key,
        seq=seq,
        organization_id=organization_id,
        project_id=project_id,
        actor_type=actor_type,
        actor_id=actor_id,
        event_type=event_type,
        payload=body,
        occurred_at=occurred_at,
        prev_hash=prev_hash,
        hash=digest,
    )
    db.add(event)
    chain.seq = seq
    chain.head_hash = digest
    db.flush()
    return event


def verify_chain(db: Session, chain_key: str) -> list[str]:
    """Recompute a chain from its first event. Returns problems; an empty list means intact."""
    problems: list[str] = []
    chain = db.execute(select(AuditChain).where(AuditChain.chain_key == chain_key)).scalar_one_or_none()
    if chain is None:
        return [f"{chain_key}: chain does not exist"]

    expected_prev = GENESIS_HASH
    last_seq = 0
    events = db.execute(
        select(AuditEvent).where(AuditEvent.chain_key == chain_key).order_by(AuditEvent.seq)
    ).scalars()
    for event in events:
        if event.seq != last_seq + 1:
            problems.append(f"{chain_key}: sequence gap before seq {event.seq}")
        if event.prev_hash != expected_prev:
            problems.append(f"{chain_key}: prev_hash mismatch at seq {event.seq}")
        recomputed = compute_hash(
            event.prev_hash,
            chain_key=event.chain_key,
            seq=event.seq,
            event_type=event.event_type,
            actor_type=event.actor_type,
            actor_id=event.actor_id,
            organization_id=event.organization_id,
            project_id=event.project_id,
            payload=event.payload,
            occurred_at=event.occurred_at,
        )
        if recomputed != event.hash:
            problems.append(f"{chain_key}: hash mismatch at seq {event.seq}")
        expected_prev = event.hash
        last_seq = event.seq

    if chain.seq != last_seq or chain.head_hash != expected_prev:
        problems.append(f"{chain_key}: chain head does not match last event")
    return problems
