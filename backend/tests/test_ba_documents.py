"""BRD and SRS drafts, assembled by the platform from the BA department's approved records (no AI)."""

from sqlalchemy import text

from tests.test_ba_lifecycle import BA, STEPS, _approve_step, _status, _w, box, env  # noqa: F401


def _documents(env):  # noqa: F811
    items = env.analyst.get(_w(env, f"/{BA}/items?kind=document")).json()["items"]
    return {i["body"]["doc_type"]: i for i in items}


def _section(doc, number):
    return next(s["content"] for s in doc["body"]["sections"] if s["heading"].startswith(f"{number}."))


def _current_content(env, step):  # noqa: F811
    item = env.item(step, env.analyst)
    return next(v for v in item["versions"] if v["id"] == item["current_version_id"])["content"]


def _to_review(env):  # noqa: F811
    env.start(scope="ba-department")
    for step in STEPS[:6]:
        _approve_step(env, step)
    assert _status(env, "ba_professional_review") == "AWAITING_HUMAN_REVIEW"


def test_the_review_step_drafts_a_brd_and_srs_from_the_approved_records(env):  # noqa: F811
    _to_review(env)
    docs = _documents(env)
    assert set(docs) == {"brd", "srs"}
    brd, srs = docs["brd"], docs["srs"]
    assert brd["provenance"] == srs["provenance"] == "system_draft"
    assert brd["title"].startswith("Business Requirements Document")
    requirement = env.analyst.get(_w(env, f"/{BA}/items?kind=requirement")).json()["items"][0]
    assert f"{requirement['key']} v{requirement['version']}" in _section(srs, 2)  # each line names its record
    assert "Booking confirmed" in _section(srs, 2)  # with its acceptance criteria
    assert "Reception staff" in _section(brd, 2) and "Double bookings" in _section(brd, 6)
    detail = env.analyst.get(_w(env, f"/items/{srs['id']}")).json()
    assert detail["versions"][0]["author_type"] == "system"  # the platform, not the AI and not a person
    assert detail["versions"][0]["reason"] == "assembled from the approved records"

    # The exact draft versions are inside what the professional approves at this step.
    content = _current_content(env, "ba_professional_review")
    assert {d["key"]: d["version"] for d in content["documents"]} == {brd["key"]: 1, srs["key"]: 1}

    # A draft must be confirmed before it can go into a package, like an AI suggestion.
    refused = env.analyst.post(_w(env, f"/{BA}/packages"), headers=env.ah, json={"item_ids": [brd["id"]]})
    assert refused.status_code == 422 and "confirm it first" in refused.json()["problems"][0]


def test_a_person_cannot_create_a_platform_draft(env):  # noqa: F811
    r = env.analyst.post(_w(env, f"/{BA}/items"), headers=env.ah, json={
        "kind": "document", "title": "BRD", "body": {"doc_type": "brd", "sections": []}, "provenance": "system_draft"})
    assert r.status_code == 422


def test_drafts_refresh_after_a_send_back_but_never_overwrite_the_professionals_edits(env):  # noqa: F811
    _to_review(env)
    docs = _documents(env)
    edited = env.analyst.put(_w(env, f"/items/{docs['srs']['id']}"), headers=env.ah, json={
        "expected_version": 1, "body": {**docs["srs"]["body"], "sections": [
            {"heading": "1. Introduction", "content": "Written by the analyst"}]}})
    assert edited.status_code == 200, edited.text

    r = env.analyst.post(_w(env, "/steps/ba_professional_review/send-back"), headers=env.ah,
                         json={"step": "ba_requirements", "note": "Add cancelling a visit"})
    assert r.status_code == 200, r.text
    for step in ["ba_requirements", "ba_user_stories", "ba_scope", "ba_requirements_review"]:
        _approve_step(env, step)
    assert _status(env, "ba_professional_review") == "AWAITING_HUMAN_REVIEW"
    after = _documents(env)
    assert after["brd"]["version"] == 2 and after["brd"]["provenance"] == "system_draft"  # refreshed
    assert after["srs"]["version"] == 2 and _section(after["srs"], 1) == "Written by the analyst"  # kept
    with env.engine.connect() as conn:
        notes = conn.execute(text("select title from ai_activity where stage_key = 'ba_professional_review'")).scalars()
        assert any("Kept the professional's edited Software Requirements Specification" in n for n in notes)
    content = _current_content(env, "ba_professional_review")
    kept = next(d for d in content["documents"] if d["doc_type"] == "srs")
    assert kept["kept_professional_edits"] is True
