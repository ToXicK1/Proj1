"""P5, D1 (RD-2 amended): on the BRD baseline (and design sign-off), the client approves after the professional, on
the same version. The approval service enforces the order; the client can never reject, and nothing changes for
projects without client approvals (test_ba_lifecycle: the owner never approves there)."""

from sqlalchemy import text

from tests.test_ba_lifecycle import STEPS, _approve_step, _status, env  # noqa: F401  (fixture)
from tests.test_portal import box  # noqa: F401  (fixture)


def _enable_client_approvals(env):  # noqa: F811
    """What the PM's start from an approved brief records in the execution's facts (app/work/brief.py)."""
    with env.engine.begin() as conn:
        conn.execute(text("update workflow_executions set config_snapshot = jsonb_set(config_snapshot, "
                          "'{facts,client_approvals}', 'true')"))


def _to_user_review(env):  # noqa: F811
    env.start(scope="ba-department")
    _enable_client_approvals(env)
    for step in STEPS[:6]:
        _approve_step(env, step)
    version = env.item("ba_professional_review", env.analyst)["current_version_id"]
    assert env.decide("ba_professional_review", version=version, client=env.analyst, headers=env.ah).status_code == 200
    asked = env.post("/deliverables/ba_user_review/questions", {"question": "Anything to change?"},
                     env.analyst, env.ah)
    assert asked.status_code == 201, asked.text
    question = next(a for a in env.get()["pending_actions"] if a["kind"] == "question"
                    and a["stage"] == "ba_user_review")
    env.post(f"/questions/{question['question_id']}/answer", {"answer": "No further input"})
    assert _status(env, "ba_user_review") == "AWAITING_HUMAN_REVIEW"


def _deliverable(env, stage):  # noqa: F811
    return next(d for d in env.get("/deliverables")["items"] if d["stage"] == stage)


def test_the_client_approves_the_brd_baseline_after_the_professional(env):  # noqa: F811
    _to_user_review(env)
    version = env.item("ba_user_review", env.analyst)["current_version_id"]
    before = _deliverable(env, "ba_user_review")
    assert before["sign_off"] == "BRD baseline" and not before["waiting_for_client"] and not before["can_decide"]
    early = env.decide("ba_user_review", version=version)
    assert early.status_code == 403  # the professional approves first

    assert env.decide("ba_user_review", version=version, client=env.analyst, headers=env.ah).status_code == 200
    assert _status(env, "ba_user_review") == "AWAITING_HUMAN_REVIEW"  # not approved until the client signs off
    again = env.decide("ba_user_review", version=version, client=env.analyst, headers=env.ah)
    assert again.status_code in (403, 409)  # the professional cannot fill the client's slot
    waiting = _deliverable(env, "ba_user_review")
    assert waiting["waiting_for_client"] and waiting["can_decide"]
    with env.engine.connect() as conn:
        assert conn.execute(text("select count(*) from notifications where kind like 'sign_off:%'")).scalar_one() == 1

    assert env.decide("ba_user_review", version=version, decision="REJECT", comment="No").status_code == 403
    assert env.decide("ba_user_review", version=version).status_code == 200
    assert _status(env, "ba_user_review") == "APPROVED"
    with env.engine.connect() as conn:
        slots = conn.execute(text("select d.policy_slot from approval_decisions d join stage_executions s "
                                  "on s.id = d.stage_execution_id where s.stage_key = 'ba_user_review' "
                                  "and d.decision = 'APPROVE' order by d.decided_at")).scalars().all()
        assert slots == ["s1", "s2"]  # the professional's slot, then the client's, on one version
        assert conn.execute(text("select status from workflow_executions")).scalar_one() == "COMPLETED"


def test_the_client_can_ask_for_changes_at_sign_off(env):  # noqa: F811
    _to_user_review(env)
    version = env.item("ba_user_review", env.analyst)["current_version_id"]
    env.decide("ba_user_review", version=version, client=env.analyst, headers=env.ah)
    r = env.decide("ba_user_review", version=version, decision="REQUEST_CHANGES", comment="Add child bookings")
    assert r.status_code == 200
    with env.engine.connect() as conn:
        assert conn.execute(text("select comment from change_requests order by created_at desc")).scalars().first()             == "Add child bookings"
    # The step is reworked (inline in tests); the professional's earlier approval no longer counts.
    assert not _deliverable(env, "ba_user_review")["waiting_for_client"]
