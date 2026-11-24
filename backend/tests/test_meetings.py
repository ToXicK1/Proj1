"""P2: the PM records client meetings (with attached documents) and validates the project intake (RD-21)."""

import pytest
from sqlalchemy import text

from app.main import create_app
from app.storage import service as storage
from tests.test_pm import _setup, _signed_in
from tests.test_storage import ACCESS, SECRET, FakeS3

MEETING = {"held_at": "2026-11-24 10:00", "status": "held", "participants": ["Olu (client)", "Pam (PM)"],
           "objectives": ["Understand the booking problem"], "raw_notes": "Phones are busy every morning.",
           "decisions": ["Start with online booking"], "open_questions": ["Which clinics first?"]}
INTAKE = {"business_problem": "Patients can only book by phone", "validation": "draft",
          "objectives": ["Cut phone bookings by half"], "target_users": ["Patients", "Reception staff"]}


@pytest.fixture
def s3():
    return FakeS3()


@pytest.fixture
def managed(settings, s3):
    app = create_app(settings.model_copy(update={
        "account_mode": "managed", "signup_mode": "shared", "storage_endpoint": "http://minio:9000",
        "storage_access_key": ACCESS, "storage_secret_key": SECRET, "storage_bucket": "aidlc-test"}))
    app.state.storage_transport = s3.transport()
    storage.ensure_bucket(app.state.settings, s3.transport())
    yield app
    app.state.engine.dispose()


def _with_pm(managed, engine):
    c, h, _, project, people = _setup(managed, engine)
    c.put(f"/api/v1/projects/{project}/manager", headers=h, json={"user_id": people["pm"]["user"]["id"]})
    pm, ph = _signed_in(managed, people["pm"])
    return people, pm, ph, f"/api/v1/projects/{project}/work"


def test_the_pm_records_a_meeting_with_its_documents(managed, engine, s3):
    _, pm, ph, w = _with_pm(managed, engine)
    meeting = pm.post(f"{w}/project_manager/items", headers=ph, json={
        "kind": "meeting", "title": "Discovery with Olu", "body": MEETING})
    assert meeting.status_code == 201, meeting.text
    item = meeting.json()
    assert item["key"] == "MTG-001" and item["body"]["decisions"] == ["Start with online booking"]

    doc = b"%PDF-1.4 the clinic's current booking form"
    up = pm.post(f"{w}/items/{item['id']}/attachments?filename=../../booking form.pdf", content=doc,
                 headers={**ph, "Content-Type": "application/pdf"})
    assert up.status_code == 201, up.text
    assert up.json()["filename"] == "booking form.pdf"  # no path parts kept
    listed = pm.get(f"{w}/items/{item['id']}/attachments").json()["items"]
    got = pm.get(f"{w}/attachments/{listed[0]['id']}")
    assert got.status_code == 200 and got.content == doc
    assert got.headers["content-disposition"].startswith("attachment;")
    assert got.headers["x-content-type-options"] == "nosniff"
    # The bytes sit in object storage under a random name, never the uploaded one.
    keys = [k for k in s3.buckets["aidlc-test"] if "/attachments/" in k]
    assert len(keys) == 1 and "booking" not in keys[0]

    html = pm.post(f"{w}/items/{item['id']}/attachments?filename=x.html", content=b"<script>",
                   headers={**ph, "Content-Type": "text/html"})
    assert html.status_code == 415
    big = pm.post(f"{w}/items/{item['id']}/attachments?filename=big.txt", content=b"x" * (10 * 1024 * 1024 + 1),
                  headers={**ph, "Content-Type": "text/plain"})
    assert big.status_code == 413
    with engine.connect() as conn:
        events = set(conn.execute(text("select event_type from audit_events")).scalars())
    assert "work.attachment_added" in events


def test_only_the_assigned_pm_writes_and_the_client_sees_none_of_it(managed, engine):
    people, pm, ph, w = _with_pm(managed, engine)
    item = pm.post(f"{w}/project_manager/items", headers=ph, json={
        "kind": "meeting", "title": "Discovery", "body": MEETING}).json()
    pm.post(f"{w}/items/{item['id']}/attachments?filename=notes.txt", content=b"internal notes",
            headers={**ph, "Content-Type": "text/plain"})
    attachment = pm.get(f"{w}/items/{item['id']}/attachments").json()["items"][0]
    other, oh = _signed_in(managed, people["other_pm"])
    assert other.post(f"{w}/project_manager/items", headers=oh, json={
        "kind": "meeting", "title": "x", "body": MEETING}).status_code == 403  # not this project's PM
    assert other.post(f"{w}/items/{item['id']}/attachments?filename=y.txt", content=b"y",
                      headers={**oh, "Content-Type": "text/plain"}).status_code == 403
    client, _ = _signed_in(managed, people["client"])
    assert client.get(f"{w}/project_manager/items").status_code == 403  # meeting notes are internal
    assert client.get(f"{w}/items/{item['id']}").status_code == 403
    assert client.get(f"{w}/attachments/{attachment['id']}").status_code == 403


def test_the_intake_is_validated_by_the_pm_once_confirmed(managed, engine):
    _, pm, ph, w = _with_pm(managed, engine)
    early = pm.post(f"{w}/project_manager/items", headers=ph, json={
        "kind": "project_intake", "title": "Clinic booking intake", "body": {**INTAKE, "validation": "validated"}})
    assert early.status_code == 422  # created as a draft first
    intake = pm.post(f"{w}/project_manager/items", headers=ph, json={
        "kind": "project_intake", "title": "Clinic booking intake", "body": INTAKE, "provenance": "assumption"}).json()
    again = pm.post(f"{w}/project_manager/items", headers=ph, json={
        "kind": "project_intake", "title": "Second", "body": INTAKE})
    assert again.status_code == 409  # one intake per project
    unconfirmed = pm.put(f"{w}/items/{intake['id']}", headers=ph, json={
        "expected_version": 1, "body": {**INTAKE, "validation": "validated"}})
    assert unconfirmed.status_code == 422  # an assumption cannot be validated
    ok = pm.put(f"{w}/items/{intake['id']}", headers=ph, json={
        "expected_version": 1, "provenance": "confirmed", "body": {**INTAKE, "validation": "validated"}})
    assert ok.status_code == 200, ok.text
    assert ok.json()["versions"][-1]["reason"] == "validated the intake"
    with engine.connect() as conn:
        assert "work.intake_validated" in set(conn.execute(text("select event_type from audit_events")).scalars())
    assert pm.get(f"{w}/client-form").status_code == 200  # the client's optional pre-meeting answers, read-only
