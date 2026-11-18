import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.audit.service import PLATFORM_CHAIN, append_event, verify_chain


def _write(engine, n: int) -> None:
    with Session(engine) as s:
        for i in range(n):
            append_event(
                s,
                chain_key=PLATFORM_CHAIN,
                event_type="test.event",
                actor_type="human",
                actor_id=str(uuid.uuid4()),
                payload={"i": i, "ok": True},
            )
        s.commit()


def test_fresh_chain_verifies(engine):
    _write(engine, 5)
    with Session(engine) as s:
        assert verify_chain(s, PLATFORM_CHAIN) == []


def test_update_and_delete_are_blocked_by_trigger(engine):
    _write(engine, 2)
    with pytest.raises(Exception, match="append-only"), engine.begin() as conn:
        conn.execute(text("UPDATE audit_events SET payload = '{}'::jsonb"))
    with pytest.raises(Exception, match="append-only"), engine.begin() as conn:
        conn.execute(text("DELETE FROM audit_events"))


def test_tampering_is_detected_when_trigger_is_bypassed(engine):
    """Simulate an administrator editing history: the hash chain must expose it."""
    _write(engine, 4)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE audit_events DISABLE TRIGGER audit_events_no_update_delete"))
        conn.execute(text("UPDATE audit_events SET payload = '{\"i\": 999}'::jsonb WHERE seq = 2"))
        conn.execute(text("ALTER TABLE audit_events ENABLE TRIGGER audit_events_no_update_delete"))
    with Session(engine) as s:
        problems = verify_chain(s, PLATFORM_CHAIN)
    assert any("hash mismatch at seq 2" in p for p in problems), problems


def test_deleted_middle_event_is_detected(engine):
    _write(engine, 3)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE audit_events DISABLE TRIGGER audit_events_no_update_delete"))
        conn.execute(text("DELETE FROM audit_events WHERE seq = 2"))
        conn.execute(text("ALTER TABLE audit_events ENABLE TRIGGER audit_events_no_update_delete"))
    with Session(engine) as s:
        problems = verify_chain(s, PLATFORM_CHAIN)
    assert problems, "a gap in the sequence must be reported"


def test_concurrent_appends_keep_chain_contiguous(engine):
    """Parallel writers serialize on the chain row: no duplicate or skipped sequence numbers."""

    def one(_: int) -> None:
        with Session(engine) as s:
            append_event(s, chain_key=PLATFORM_CHAIN, event_type="test.parallel", actor_type="system")
            s.commit()

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(one, range(40)))
    with Session(engine) as s:
        assert verify_chain(s, PLATFORM_CHAIN) == []
