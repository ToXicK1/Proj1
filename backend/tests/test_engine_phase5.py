"""Phase 5 engine: every transition, parallel branches and joins, conditions, recovery and lock-free work."""

import itertools
import threading
import time
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.jobs import service as jobs
from app.jobs.models import Job
from app.portal import service as portal
from app.workflows import service
from app.workflows.compiler import CompileError, compile_workflow
from app.workflows.models import StageDependency, StageExecution, StageTransition, WorkflowExecution
from app.workflows.state_machine import (
    EDGES,
    ActorType,
    InvalidTransition,
    StageStatus,
    check_transition,
)
from app.workflows.work import KNOWN_WORK, WORK_FUNCTIONS
from tests.test_workflow_engine import _owner_and_project

S = StageStatus
A = ActorType


# 1. Every transition, valid and invalid --------------------------------------------------------------------------

def test_every_status_pair_and_actor_is_decided_by_the_table_alone():
    checked = 0
    for frm, to, actor in itertools.product(S, S, A):
        allowed = actor in EDGES.get((frm, to), frozenset())
        if allowed:
            check_transition(frm, to, actor)
        else:
            with pytest.raises(InvalidTransition):
                check_transition(frm, to, actor)
        checked += 1
    assert checked == len(S) ** 2 * len(A)


def test_ai_agents_and_providers_hold_no_edge_and_only_people_decide():
    for (frm, to), actors in EDGES.items():
        assert A.AI_AGENT not in actors and A.PROVIDER not in actors, (frm, to)
    human_only = {S.APPROVED, S.REJECTED, S.CANCELLED, S.AWAITING_USER_INPUT}
    for (frm, to), actors in EDGES.items():
        if to in human_only:
            assert actors == frozenset({A.HUMAN}), (frm, to)
    assert EDGES[(S.RUNNING, S.READY)] == frozenset({A.SYSTEM})  # recovery is the system's, never a person's shortcut
    assert EDGES[(S.AWAITING_USER_INPUT, S.CHANGES_REQUESTED)] == frozenset({A.HUMAN})


def _project_with(client, engine, spec, email=None):
    csrf, project = _owner_and_project(client, engine, email or f"p5-{uuid.uuid4().hex[:8]}@example.com")
    with Session(engine) as s:
        version = service.publish_version(s, spec)
        version_id = version.id
    r = client.post(f"/api/v1/projects/{project['id']}/workflow-executions",
                    json={"workflow_version_id": str(version_id)}, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 201, r.text
    return uuid.UUID(r.json()["id"]), project, csrf


def _flow(execution="parallel", **conditions):
    def stage(sid, work, keys, deps=(), **extra):
        return {"id": sid, "name": sid.upper(), "work": work, "human_gate": False, "depends_on": list(deps),
                "output_required_keys": keys, **extra}
    stages = [
        stage("a", "workspace_scaffold", ["project_name"]),
        stage("b", "workspace_detection", ["project_kind"], ["a"]),
        stage("c", "state_initialization", ["brief_items"], ["a"]),
        stage("d", "workspace_scaffold", ["project_name"], ["b", "c"]),
    ]
    for sid, cond in conditions.items():
        next(s for s in stages if s["id"] == sid)["condition"] = cond
    return {"key": f"p5-{uuid.uuid4().hex[:10]}", "name": "Phase 5 flow", "execution": execution, "stages": stages}


def _statuses(engine, execution_id):
    with Session(engine) as s:
        return dict(s.execute(select(StageExecution.stage_key, StageExecution.status)
                              .where(StageExecution.workflow_execution_id == execution_id)).all())


def test_every_edge_and_every_non_edge_against_the_database(client, engine):
    execution_id, _, _ = _project_with(client, engine, _flow())
    tried = 0
    with Session(engine) as db:
        for frm, to, actor in itertools.product(S, S, (A.SYSTEM, A.HUMAN, A.AI_AGENT, A.PROVIDER)):
            db.execute(text("update stage_executions set status = :s where workflow_execution_id = :e and "
                            "stage_key = 'd'"), {"s": frm.value, "e": execution_id})
            before = db.execute(text("select count(*) from stage_transitions")).scalar()
            allowed = actor in EDGES.get((frm, to), frozenset())
            try:
                service.transition_stage(db, execution_id=execution_id, stage_key="d", to_status=to, actor=actor,
                                         approval_satisfied=True, commit=False)
                assert allowed, (frm, to, actor)
                assert db.execute(text("select count(*) from stage_transitions")).scalar() == before + 1
            except AppError as exc:
                assert not allowed, (frm, to, actor, exc.code)
                assert exc.code == "invalid_transition"
            db.rollback()
            tried += 1
    assert tried == len(S) ** 2 * 4


def test_approval_needs_a_satisfied_policy_even_on_a_valid_edge(client, engine):
    execution_id, _, _ = _project_with(client, engine, _flow())
    with Session(engine) as db:
        db.execute(text("update stage_executions set status = 'AWAITING_HUMAN_REVIEW' where stage_key = 'a' "
                        "and workflow_execution_id = :e"), {"e": execution_id})
        with pytest.raises(AppError) as refused:
            service.transition_stage(db, execution_id=execution_id, stage_key="a", to_status=S.APPROVED,
                                     actor=A.HUMAN, commit=False)
        assert refused.value.code == "approval_required"


# 2. Parallel branches, joins and the dependency table ---------------------------------------------------------------

def _worker_settings(app):
    return app.state.settings.model_copy(update={"jobs_inline": False})


def _queued_stages(app):
    with app.state.session_factory() as db:
        return sorted(j.payload["stage_key"] for j in db.execute(
            select(Job).where(Job.kind == "portal.stage", Job.status == "queued")).scalars())


def _run_one(app, worker="w"):
    return jobs.run_one(app.state.session_factory, _worker_settings(app), None, worker)


def test_the_dependency_graph_is_stored_as_rows(client, engine):
    execution_id, _, _ = _project_with(client, engine, _flow())
    with Session(engine) as db:
        rows = {(r.stage_key, r.depends_on) for r in db.execute(
            select(StageDependency).where(StageDependency.workflow_execution_id == execution_id)).scalars()}
    assert rows == {("b", "a"), ("c", "a"), ("d", "b"), ("d", "c")}


def test_independent_branches_are_dispatched_together_and_the_join_waits_for_both(app, client, engine):
    execution_id, _, _ = _project_with(client, engine, _flow("parallel"))
    portal.drive(app.state.session_factory, _worker_settings(app), None, execution_id)
    assert _queued_stages(app) == ["a"]
    assert _run_one(app)  # a
    assert _queued_stages(app) == ["b", "c"]  # both branches at once
    assert _run_one(app)  # one branch
    assert _statuses(engine, execution_id)["d"] == "NOT_STARTED"  # the join still waits for the other branch
    assert _run_one(app)
    assert _queued_stages(app) == ["d"]
    assert _run_one(app)
    assert set(_statuses(engine, execution_id).values()) == {"COMPLETED"}


def test_a_sequential_workflow_runs_one_stage_at_a_time(app, client, engine):
    execution_id, _, _ = _project_with(client, engine, _flow("sequential"))
    portal.drive(app.state.session_factory, _worker_settings(app), None, execution_id)
    _run_one(app)
    assert _queued_stages(app) == ["b"]  # only the first of the ready branches


def test_two_workers_really_run_two_branches_at_the_same_time(app, client, engine, monkeypatch):
    execution_id, _, _ = _project_with(client, engine, _flow("parallel"))
    spans: dict[str, tuple[float, float]] = {}
    slow = {}

    def slowly(name, real):
        def run(ctx):
            began = time.monotonic()
            time.sleep(1.5)
            out = real(ctx)
            spans[name] = (began, time.monotonic())
            return out
        return run

    for key, name in (("workspace_detection", "b"), ("state_initialization", "c")):
        slow[key] = WORK_FUNCTIONS[key]
        monkeypatch.setitem(WORK_FUNCTIONS, key, slowly(name, slow[key]))
    portal.drive(app.state.session_factory, _worker_settings(app), None, execution_id)
    _run_one(app)  # a; b and c are now queued
    threads = [threading.Thread(target=_run_one, args=(app, f"worker-{i}")) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    (b0, b1), (c0, c1) = spans["b"], spans["c"]
    assert b0 < c1 and c0 < b1  # the two branches overlapped: neither waited for the other's lock
    assert _statuses(engine, execution_id)["d"] == "READY"  # and the join saw both finish, exactly once
    with Session(engine) as db:
        to_ready = db.execute(select(StageTransition).join(StageExecution).where(
            StageExecution.workflow_execution_id == execution_id, StageExecution.stage_key == "d",
            StageTransition.to_status == "READY")).scalars().all()
    assert len(to_ready) == 1


def test_no_lock_is_held_while_a_stage_does_its_work(app, client, engine, monkeypatch):
    execution_id, _, _ = _project_with(client, engine, _flow("parallel"))
    seen = {}
    real = WORK_FUNCTIONS["workspace_scaffold"]

    def checking(ctx):
        with Session(engine) as other:  # another request trying to change the same execution right now
            other.execute(text("set local lock_timeout = '1s'"))
            other.execute(select(WorkflowExecution).where(WorkflowExecution.id == execution_id).with_for_update())
            seen["status"] = other.execute(select(StageExecution.status).where(
                StageExecution.workflow_execution_id == execution_id, StageExecution.stage_key == "a")).scalar_one()
            other.rollback()
        return real(ctx)

    monkeypatch.setitem(WORK_FUNCTIONS, "workspace_scaffold", checking)
    with Session(engine) as db:
        service.run_deterministic_stage(db, execution_id=execution_id, stage_key="a")
    assert seen["status"] == "RUNNING"  # the claim was committed and no lock blocked the other request


# 3. Conditions -----------------------------------------------------------------------------------------------------

def test_a_false_condition_skips_the_stage_and_its_dependents_still_run(app, client, engine):
    flow = _flow("parallel", b={"fact": "project_type", "equals": "Mobile Application"},
                 c={"artifact": "a", "field": "project_name", "present": True})
    execution_id, _, _ = _project_with(client, engine, flow)  # the project is a SaaS Platform
    portal.drive(app.state.session_factory, _worker_settings(app), None, execution_id)
    while _run_one(app):
        pass
    assert _statuses(engine, execution_id) == {"a": "COMPLETED", "b": "SKIPPED", "c": "COMPLETED", "d": "COMPLETED"}
    with Session(engine) as db:
        reason = db.execute(select(StageTransition.reason).join(StageExecution).where(
            StageExecution.workflow_execution_id == execution_id, StageExecution.stage_key == "b",
            StageTransition.to_status == "SKIPPED")).scalar_one()
    assert reason == "condition not met: project_type is 'SaaS Platform'"


def test_a_root_stage_with_a_false_condition_is_skipped_at_the_start(client, engine):
    flow = _flow("parallel", a={"not": {"fact": "project_type", "in": ["SaaS Platform", "Web Application"]}})
    execution_id, _, _ = _project_with(client, engine, flow)
    statuses = _statuses(engine, execution_id)
    assert statuses["a"] == "SKIPPED" and statuses["b"] == "READY" and statuses["c"] == "READY"


@pytest.mark.parametrize(("condition", "fragment"), [
    ({"fact": "weather", "equals": "sunny"}, "unknown fact"),
    ({"artifact": "d", "field": "x", "present": True}, "is not upstream"),
    ({"fact": "scope", "equals": "poc", "in": ["mvp"]}, "exactly one of"),
    ({"fact": "scope", "in": []}, "non-empty list"),
    ({"fact": "scope", "present": "yes"}, "true or false"),
    ({"all": []}, "non-empty list"),
    ({"not": {"not": {"not": {"not": {"not": {"fact": "scope", "present": True}}}}}}, "nested more than"),
    ({"fact": "scope", "equals": {"$gt": 1}}, "only text, numbers"),
    ("scope == 'poc'", "valid dictionary"),
])
def test_bad_conditions_are_refused_before_anything_runs(condition, fragment):
    flow = _flow("parallel", b=condition)
    with pytest.raises(CompileError) as refused:
        compile_workflow(flow, known_work=set(KNOWN_WORK))
    assert any(fragment in p for p in refused.value.problems), refused.value.problems


def test_mandatory_and_built_stages_can_never_be_conditional():
    flow = _flow("parallel", b={"fact": "scope", "present": True})
    flow["stages"][1]["mandatory"] = True
    with pytest.raises(CompileError, match="mandatory stage can never be skipped"):
        compile_workflow(flow, known_work=set(KNOWN_WORK))


# 4. Recovery and ownership of a run --------------------------------------------------------------------------------

def _claim_and_abandon(engine, execution_id, key):
    """Leaves a stage RUNNING, owned by a job that no longer exists: what a crash leaves behind."""
    with Session(engine) as db:
        stage = service.transition_stage(db, execution_id=execution_id, stage_key=key, to_status=S.RUNNING,
                                         actor=A.SYSTEM, commit=False)
        stage.run_job_id = uuid.uuid4()
        db.commit()


def test_an_abandoned_run_is_recovered_by_the_next_stage_job(app, client, engine):
    execution_id, _, _ = _project_with(client, engine, _flow("parallel"))
    _claim_and_abandon(engine, execution_id, "a")
    portal.drive(app.state.session_factory, _worker_settings(app), None, execution_id)
    assert _queued_stages(app) == ["a"]  # the dispatcher sees the dead owner and queues the stage again
    _run_one(app)
    assert _statuses(engine, execution_id)["a"] == "COMPLETED"
    with Session(engine) as db:
        moves = db.execute(select(StageTransition.from_status, StageTransition.to_status).join(StageExecution).where(
            StageExecution.workflow_execution_id == execution_id, StageExecution.stage_key == "a")
            .order_by(StageTransition.id)).all()
    assert [tuple(m) for m in moves][:3] == [("READY", "RUNNING"), ("RUNNING", "READY"), ("READY", "RUNNING")]


def test_a_run_still_owned_by_a_live_job_is_left_alone(app, client, engine):
    execution_id, _, _ = _project_with(client, engine, _flow("parallel"))
    with app.state.session_factory() as db:
        live = jobs.enqueue(db, "portal.stage", {"execution_id": str(execution_id), "stage_key": "a"})
        db.commit()
        jobs.claim(db, "busy-worker", 600)
    with Session(engine) as db:
        stage = service.transition_stage(db, execution_id=execution_id, stage_key="a", to_status=S.RUNNING,
                                         actor=A.SYSTEM, commit=False)
        stage.run_job_id = live
        db.commit()
    portal.drive(app.state.session_factory, _worker_settings(app), None, execution_id)
    assert _queued_stages(app) == []  # nothing else is started while the run is alive
    assert _statuses(engine, execution_id)["a"] == "RUNNING"


def test_an_interrupted_rework_returns_to_changes_requested_without_using_a_loop(client, engine):
    execution_id, _, _ = _project_with(client, engine, _flow("parallel"))
    with Session(engine) as db:
        db.execute(text("update stage_executions set status = 'RUNNING', rework_count = 1 where stage_key = 'a' "
                        "and workflow_execution_id = :e"), {"e": execution_id})
        db.commit()
    with Session(engine) as db:
        stage = service.recover_stage(db, execution_id=execution_id, stage_key="a", reason="test")
        assert stage.status == "CHANGES_REQUESTED" and stage.rework_count == 0


def test_only_an_interrupted_run_can_be_recovered(client, engine):
    execution_id, _, _ = _project_with(client, engine, _flow("parallel"))
    with Session(engine) as db, pytest.raises(AppError, match="interrupted run"):
        service.recover_stage(db, execution_id=execution_id, stage_key="a", reason="test")


def test_a_run_that_lost_its_stage_discards_its_result(client, engine, monkeypatch):
    execution_id, _, _ = _project_with(client, engine, _flow("parallel"))
    real = WORK_FUNCTIONS["workspace_scaffold"]

    def meanwhile_cancelled(ctx):
        with Session(engine) as other:  # a person cancels the stage while the work is in progress
            service.transition_stage(other, execution_id=execution_id, stage_key="a", to_status=S.CANCELLED,
                                     actor=A.HUMAN, actor_id="someone")
        return real(ctx)

    monkeypatch.setitem(WORK_FUNCTIONS, "workspace_scaffold", meanwhile_cancelled)
    with Session(engine) as db, pytest.raises(service.Superseded):
        service.run_deterministic_stage(db, execution_id=execution_id, stage_key="a")
    assert _statuses(engine, execution_id)["a"] == "CANCELLED"
    with Session(engine) as db:
        assert db.execute(text("select count(*) from artifact_versions av join artifacts ar on ar.id = av.artifact_id "
                               "where ar.project_id = (select project_id from workflow_executions where id = :e)"),
                          {"e": execution_id}).scalar() == 0


def test_interrupted_checks_resume_without_redoing_the_work(client, engine):
    flow = _flow("parallel")
    execution_id, _, _ = _project_with(client, engine, flow)
    with Session(engine) as db:  # the work was recorded, then the worker died during the checks
        service.transition_stage(db, execution_id=execution_id, stage_key="a", to_status=S.RUNNING, actor=A.SYSTEM,
                                 commit=False)
        service.transition_stage(db, execution_id=execution_id, stage_key="a", to_status=S.AI_COMPLETED,
                                 actor=A.SYSTEM, output={"project_name": "x", "project_type": "y"}, commit=False)
        service.transition_stage(db, execution_id=execution_id, stage_key="a", to_status=S.VALIDATING,
                                 actor=A.SYSTEM, commit=False)
        db.commit()
    with Session(engine) as db:
        assert service.resume_validation(db, execution_id=execution_id, stage_key="a").status == "COMPLETED"
    with Session(engine) as db:
        assert db.execute(text("select count(*) from artifact_versions av join artifacts ar on ar.id = av.artifact_id "
                               "where ar.kind = 'a'")).scalar() == 1  # still the one version
