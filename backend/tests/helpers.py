import re

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.notifications.models import EmailOutbox

PASSWORD = "correct-horse-battery-staple"


def latest_email(engine: Engine, kind: str, recipient: str) -> str:
    with Session(engine) as s:
        row = (
            s.execute(
                select(EmailOutbox)
                .where(EmailOutbox.kind == kind, EmailOutbox.recipient == recipient)
                .order_by(EmailOutbox.id.desc())
            )
            .scalars()
            .first()
        )
    assert row is not None, f"no {kind} email for {recipient}"
    return row.body


def verify_token_from(engine: Engine, recipient: str) -> str:
    body = latest_email(engine, "verify_email", recipient)
    match = re.search(r"token=([A-Za-z0-9_\-]+)", body)
    assert match, "verification link not found"
    return match.group(1)


def signup_verify_login(client, engine, email: str, name: str = "Test User", password: str = PASSWORD) -> str:
    """Register, verify, sign in. Returns the CSRF token for the session."""
    r = client.post("/api/v1/auth/signup", json={"email": email, "password": password, "display_name": name})
    assert r.status_code == 202, r.text
    token = verify_token_from(engine, email)
    r = client.post("/api/v1/auth/verify-email", json={"token": token})
    assert r.status_code == 200, r.text
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["csrf_token"]
