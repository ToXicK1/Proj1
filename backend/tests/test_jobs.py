"""The durable job queue and worker (RD-4): claiming, leases, retries, recovery and crash safety."""

import threading
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select, text, update

from app.core import correlation
from app.jobs import service as jobs
from app.jobs.models import Job
from app.workflows.models import StageExecution
from tests.test_portal import FIRST, Portal, _email, box  # noqa: F401  (fixture)


@pytest.fixture
def factory(app):
    return app.state.session_factory


def _job(factory, job_id):
    with factory() as db:
        return db.get(Job, job_id)


def _queue(factory, kind="test.noop", payload=None, **kw):
    with factory() as db:
        job_id = jobs.enqueue(db, kind, payload or {}, **kw)
        db.commit()
        return job_id


def _expire(factory, job_id):
    with factory() as db:
        db.execute(update(Job).where(Job.id == job_id).values(locked_until=datetime.now(UTC) - timedelta(seconds=1)))
        db.commit()


def test_one_waiting_job_per_subject(factory):
    first = _queue(factory, dedupe_key="drive:x")
    assert _queue(factory, dedupe_key="drive:x") is None  # joins the waiting job
    with factory() as db:
        assert jobs.claim(db, "w1", 60).id == first
    # Once it runs, new work for the same subject can wait behind it: it may arrive after the run has looked.
    assert _queue(factory, dedupe_key="drive:x") is not None


def test_a_job_held_by_one_worker_is_skipped_by_another(factory):
    job_id = _queue(factory)
    holder = factory()
    holder.execute(select(Job).where(Job.id == job_id).with_for_update())  # another worker is claiming it
    try:
        with factory() as db:
            assert jobs.claim(db, "w2", 60) is None
    finally:
        holder.rollback()
        holder.close()
    with factory() as db:
        assert jobs.claim(db, "w2", 60).id == job_id


def test_a_dead_workers_job_is_taken_back_and_the_late_finisher_is_ignored(factory):
    job_id = _queue(factory)
    with factory() as db:
        assert jobs.claim(db, "w1", 60).id == job_id
    with factory() as db:
        assert jobs.claim(db, "w2", 60) is None  # the lease still holds
    _expire(factory, job_id)
    with factory() as db:
        retaken = jobs.claim(db, "w2", 60)
        assert retaken.id == job_id and retaken.attempts == 2 and retaken.locked_by == "w2"
    with factory() as db:
        assert not jobs.mark_done(db, job_id, "w1")  # the first worker came back too late
        assert jobs.mark_done(db, job_id, "w2")
        db.commit()
    assert _job(factory, job_id).status == "done"


def test_a_job_whose_last_attempt_died_is_failed_not_run_again(factory):
    job_id = _queue(factory, max_attempts=1)
    with factory() as db:
        jobs.claim(db, "w1", 60)
    _expire(factory, job_id)
    with factory() as db:
        assert jobs.claim(db, "w2", 60) is None
    job = _job(factory, job_id)
    assert job.status == "failed" and "last allowed attempt" in job.last_error


def test_failures_are_retried_with_a_pause_then_reported(factory, settings):
    job_id = _queue(factory, "test.boom", max_attempts=2)

    def boom(ctx):
        raise RuntimeError("provider exploded")

    assert jobs.run_one(factory, settings, None, "w1", {"test.boom": boom})
    job = _job(factory, job_id)
    assert job.status == "queued" and job.attempts == 1 and "provider exploded" in job.last_error
    assert job.run_after > datetime.now(UTC) + timedelta(seconds=5)  # backs off instead of hammering
    assert not jobs.run_one(factory, settings, None, "w1", {"test.boom": boom})  # not due yet
    with factory() as db:
        db.execute(update(Job).where(Job.id == job_id).values(run_after=datetime.now(UTC)))
        db.commit()
    jobs.run_one(factory, settings, None, "w1", {"test.boom": boom})
    job = _job(factory, job_id)
    assert job.status == "failed" and job.attempts == 2 and job.finished_at is not None


def test_an_unknown_kind_is_recorded_as_a_failure(factory, settings):
    job_id = _queue(factory, "test.nobody", max_attempts=1)
    jobs.run_one(factory, settings, None, "w1", {})
    assert "no handler" in _job(factory, job_id).last_error


def test_the_request_id_follows_the_job(factory, settings):
    token = correlation.bind("req-1234567890")
    try:
        job_id = _queue(factory, "test.seen")
    finally:
        correlation.reset(token)
    seen = []
    jobs.run_one(factory, settings, None, "w1", {"test.seen": lambda ctx: seen.append(correlation.current())})
    assert seen == ["req-1234567890"]
    job = _job(factory, job_id)
    assert job.correlation_id == "req-1234567890" and job.status == "done"


def test_the_heartbeat_keeps_the_lease_and_only_for_its_owner(factory):
    job_id = _queue(factory)
    with factory() as db:
        before = jobs.claim(db, "w1", 5).locked_until
    assert jobs.heartbeat(factory, job_id, "w1", 600)
    assert _job(factory, job_id).locked_until > before + timedelta(seconds=500)
    assert not jobs.heartbeat(factory, job_id, "w2", 600)


def test_a_long_job_keeps_its_lease_while_it_runs(factory, settings):
    """With a short lease, a job running longer than the lease is not taken by a second worker."""
    job_id = _queue(factory, "test.slow")
    quick = settings.model_copy(update={"job_lease_seconds": 3.0})
    release = threading.Event()
    started = threading.Event()

    def slow(ctx):
        started.set()
        release.wait(10)

    runner = threading.Thread(target=jobs.run_one, args=(factory, quick, None, "w1", {"test.slow": slow}))
    runner.start()
    try:
        assert started.wait(10)
        threading.Event().wait(4.5)  # longer than the lease; the heartbeat (every second) renews it
        with factory() as db:
            assert jobs.claim(db, "w2", 3) is None
    finally:
        release.set()
        runner.join(10)
    assert _job(factory, job_id).status == "done"


# A real stage ---------------------------------------------------------------------------------------------------

class Died(BaseException):
    """Stands in for the process being killed: nothing in the platform catches it."""


@pytest.fixture
def manual(client, engine, settings, box):  # noqa: F811
    """A project whose queued work does not run until the test runs it, as with a separate worker."""
    portal = Portal(client, engine, settings, _email())
    portal.box = box
    portal.setup_team()
    worker_settings = portal.settings.model_copy(update={"jobs_inline": False})
    client.app.state.settings = worker_settings
    portal.worker_settings = worker_settings
    return portal


def _first_stage(factory):
    with factory() as db:
        return db.execute(select(StageExecution).where(StageExecution.stage_key == FIRST)).scalar_one()


def test_starting_delivery_only_queues_the_work(manual, factory):
    manual.start()
    with factory() as db:
        queued = db.execute(select(Job)).scalars().all()
    assert [(j.kind, j.status) for j in queued] == [("portal.drive", "queued")]
    assert queued[0].project_id is not None and queued[0].organization_id is not None
    with factory() as db:  # nothing ran inside the request: no stage has moved past its starting state
        statuses = set(db.execute(select(StageExecution.status)).scalars())
        versions = db.execute(text("select count(*) from artifact_versions")).scalar()
    assert statuses == {"READY", "NOT_STARTED"} and versions == 0


def test_a_worker_killed_mid_stage_leaves_nothing_half_done_and_another_finishes_it(manual, factory):
    manual.start()
    (job_id,) = [j.id for j in _all_jobs(factory)]

    def killed(request: httpx.Request) -> httpx.Response:
        raise Died()

    with pytest.raises(Died):
        jobs.run_one(factory, manual.worker_settings, httpx.MockTransport(killed), "worker-a")
    # The setup steps before it had already committed; the AI stage that was running rolled back with the process.
    assert _first_stage(factory).status == "READY"
    assert _versions_of(factory, FIRST) == 0
    assert _job(factory, job_id).status == "running"  # still held by the dead worker until its lease ends

    _expire(factory, job_id)
    assert jobs.run_one(factory, manual.worker_settings, manual.model.transport(), "worker-b")
    job = _job(factory, job_id)
    assert job.status == "done" and job.attempts == 2
    assert manual.step_status(FIRST) == "Awaiting Review"
    assert _versions_of(factory, FIRST) == 1  # done once, not twice


def _versions_of(factory, stage_key):
    with factory() as db:
        return db.execute(text("select count(*) from artifact_versions v join artifacts a on a.id = v.artifact_id "
                               "where a.kind = :k"), {"k": stage_key}).scalar()


def _all_jobs(factory):
    with factory() as db:
        return db.execute(select(Job)).scalars().all()


def test_the_sweep_queues_stalled_work_once(manual, factory, settings):
    manual.start()
    with factory() as db:  # the queued job was lost (for example the API died after committing)
        db.execute(text("delete from jobs"))
        db.execute(update(StageExecution).values(updated_at=datetime.now(UTC) - timedelta(hours=1)))
        db.commit()
    with factory() as db:
        assert jobs.sweep(db, settings) == [f"drive:{_first_stage(factory).workflow_execution_id}"]
    with factory() as db:
        assert jobs.sweep(db, settings) == []  # already waiting
    assert jobs.run_pending(factory, manual.worker_settings, manual.model.transport()) == 1
    assert manual.step_status(FIRST) == "Awaiting Review"
    with factory() as db:
        assert jobs.sweep(db, settings) == []  # now at a human gate: nothing to recover


def test_recent_work_is_left_alone_by_the_sweep(manual, factory, settings):
    manual.start()
    with factory() as db:
        db.execute(text("delete from jobs"))
        db.commit()
    with factory() as db:
        assert jobs.sweep(db, settings) == []  # inside the grace period the request's own job may still arrive


def test_jobs_inline_is_refused_outside_tests(settings):
    with pytest.raises(RuntimeError, match="JOBS_INLINE"):
        settings.model_copy(update={"app_env": "production", "secret_key": "x" * 40}).assert_safe_for_environment()
