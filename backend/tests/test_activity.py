"""The live AI activity log: what it records, when it can be read, and who may read it."""

import json

import httpx
import pytest
from sqlalchemy import select, text

from app.activity.models import AiActivity
from app.jobs import service as jobs
from app.workflows.models import StageExecution
from tests.test_collab import _overseer, _owner_only
from tests.test_jobs import manual  # noqa: F401  (fixture)
from tests.test_portal import FIRST, box, env  # noqa: F401  (fixtures)
from tests.test_sandbox_flow import CODE, _reach_code


def _feed(client, env):  # noqa: F811
    r = client.get(f"{env.base}/activity")
    assert r.status_code == 200, r.text
    return r.json()


def _run(env):  # noqa: F811
    factory = env.client.app.state.session_factory
    return jobs.run_pending(factory, env.worker_settings, env.model.transport())


def test_the_log_tells_the_story_of_a_stage_in_order(manual):  # noqa: F811
    manager = _overseer(manual, "project_manager")[0]
    manual.start()
    assert _run(manual) >= 1
    feed = _feed(manager, manual)
    titles = [i["title"] for i in reversed(feed["items"])]
    assert titles[0] == "Planning the next steps: started" and titles[-1].endswith(": finished")
    assert "Running a step: started" in titles  # each stage runs as its own job
    first = [i for i in reversed(feed["items"]) if i["stage"] == FIRST]
    kinds = [i["kind"] for i in first]
    assert kinds[:4] == ["stage", "context", "model_call", "output"]
    assert kinds[-2:] == ["review", "result"]
    context = first[1]["detail"]
    assert context["brief"] and context["must_return"] == ["problem_statement", "target_users", "desired_outcomes",
                                                           "open_questions"]
    output = next(i for i in first if i["kind"] == "output")["detail"]
    assert {f["key"] for f in output["fields"]} == set(context["must_return"])
    assert output["tokens"] == {"in": 20, "out": 10}
    assert first[-1]["title"] == "Intent Capture & Framing is ready and waiting for a professional's approval"
    assert all(i["profile"] == "business_analyst" for i in first)
    assert feed["jobs"] == []  # nothing waiting now


def test_entries_can_be_read_while_the_stage_is_still_running(manual):  # noqa: F811
    factory = manual.client.app.state.session_factory
    manual.start()
    seen = {}
    real = manual.model.transport()

    def watching(request: httpx.Request) -> httpx.Response:
        if "stage" not in seen:  # the first model call: look at the database from outside the stage's transaction
            with factory() as db:
                seen["stage"] = db.execute(select(StageExecution.status)
                                           .where(StageExecution.stage_key == FIRST)).scalar_one()
                seen["notes"] = db.execute(select(AiActivity.kind).where(AiActivity.stage_key == FIRST)
                                           .order_by(AiActivity.created_at)).scalars().all()
        return real.handle_request(request)

    jobs.run_pending(factory, manual.worker_settings, httpx.MockTransport(watching))
    assert seen["stage"] == "RUNNING"  # the claim is committed before the AI works, so the stage shows as running
    assert seen["notes"] == ["stage", "context", "model_call"]  # and the log already shows what it is doing


def test_owners_never_see_the_log_and_professionals_see_only_their_departments(manual):  # noqa: F811
    analyst, _ = manual.holder("business_analyst")
    devops, _ = manual.holder("devops_release")
    admin = _overseer(manual, "org_admin")[0]
    outsider, _, _ = manual.person()
    _owner_only(manual)
    manual.start()
    _run(manual)
    assert manual.client.get(f"{manual.base}/activity").status_code == 403
    assert outsider.get(f"{manual.base}/activity").status_code == 404
    everything = _feed(admin, manual)["items"]
    assert {i["profile"] for i in everything} >= {"business_analyst", "devops_release"}
    mine = _feed(analyst, manual)["items"]
    assert {i["profile"] for i in mine} == {"business_analyst", None}
    assert all(i["kind"] == "job" for i in mine if i["profile"] is None)
    assert {i["profile"] for i in _feed(devops, manual)["items"]} == {"devops_release", None}


def test_generated_code_is_shown_only_to_people_allowed_to_see_code(env):  # noqa: F811
    _reach_code(env)
    admin = _overseer(env, "org_admin")[0]
    manager = _overseer(env, "project_manager")[0]
    code = [i for i in _feed(admin, env)["items"] if i["stage"] == CODE]
    files = next(f for i in code if i["kind"] == "output" for f in i["detail"]["fields"] if f["key"] == "source_files")
    assert [f["path"] for f in files["files"]] == ["calc.py", "test_calc.py"]
    assert all(f["lines"] > 0 and f["bytes"] > 0 for f in files["files"])
    checks = next(i for i in code if i["kind"] == "checks")
    assert checks["title"] == "Built and tested the generated code in the sandbox: build passed, tests passed"
    assert "def add" in json.dumps(code)  # administrators may see code, including inside the live replies
    seen_by_manager = json.dumps(_feed(manager, env)["items"])
    assert "def add" not in seen_by_manager  # project managers oversee the work but do not see source code
    hidden = [i for i in _feed(manager, env)["items"] if i["kind"] == "model_call" and i["detail"].get("hidden")]
    assert hidden and all(i["detail"]["text"] == "" and "prompt" not in i["detail"] for i in hidden)


def test_a_model_outage_is_recorded_plainly(env):  # noqa: F811
    env.setup_team()
    admin = _overseer(env, "org_admin")[0]
    env.model.down = True
    env.start()
    feed = [i for i in _feed(admin, env)["items"] if i["stage"] == FIRST]
    assert any(i["kind"] == "model_error" for i in feed)
    assert feed[0]["kind"] == "result" and feed[0]["detail"]["status"] in ("FAILED", "BLOCKED")


def test_writing_the_log_never_breaks_the_work(manual, monkeypatch):  # noqa: F811
    def broken(*args, **kwargs):
        raise RuntimeError("log table unavailable")

    monkeypatch.setattr("app.activity.service.AiActivity", broken)
    manual.start()
    assert _run(manual) >= 1
    assert manual.step_status(FIRST) == "Awaiting Review"
    with manual.engine.connect() as conn:
        assert conn.execute(text("select count(*) from ai_activity")).scalar() == 0


# Streaming and live model calls --------------------------------------------------------------------------------------

def _sse(*chunks, usage=(30, 12)):
    lines = [json.dumps({"model": "m", "choices": [{"delta": c, "finish_reason": None}]}) for c in chunks]
    lines.append(json.dumps({"model": "m", "choices": [], "usage": {"prompt_tokens": usage[0],
                                                                    "completion_tokens": usage[1]}}))
    return "".join(f"data: {line}\n\n" for line in lines) + "data: [DONE]\n\n"


def test_the_adapter_streams_text_and_separates_reasoning():
    from app.providers.adapters import OpenAICompatibleAdapter
    from app.providers.base import CompletionRequest

    body = _sse({"reasoning": "Need the problem first. "}, {"content": "<think>check keys</think>"},
                {"content": '{"a": '}, {"content": "1}"})
    seen = []
    adapter = OpenAICompatibleAdapter(client=httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, headers={"content-type": "text/event-stream"}, text=body))),
        base_url="http://model/v1")
    result = adapter.complete(CompletionRequest(system="s", user="u", model="m",
                                                on_delta=lambda k, c: seen.append((k, c))))
    assert result.text == '{"a": 1}'
    assert result.thinking == "Need the problem first. check keys"
    assert (result.usage.input_tokens, result.usage.output_tokens) == (30, 12)
    assert [k for k, _ in seen] == ["thinking", "thinking", "text", "text"]


def test_a_model_call_is_visible_while_it_streams(manual, monkeypatch):  # noqa: F811
    monkeypatch.setattr("app.activity.service.FLUSH_SECONDS", 0)
    factory = manual.client.app.state.session_factory
    manual.start()
    real = manual.model.transport()
    seen = {}

    def streaming(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        if not payload.get("stream"):
            return real.handle_request(request)
        answer = json.loads(json.loads(real.handle_request(httpx.Request(
            "POST", request.url, json={**payload, "stream": False})).content)["choices"][0]["message"]["content"])
        text = json.dumps(answer)
        half = len(text) // 2

        def chunks():
            yield f"data: {json.dumps({'choices': [{'delta': {'content': text[:half]}}]})}\n\n".encode()
            if "mid" not in seen:  # between the two halves: what does someone watching see?
                with factory() as db:
                    row = db.execute(select(AiActivity).where(AiActivity.kind == "model_call")
                                     .order_by(AiActivity.created_at.desc())).scalars().first()
                    seen["mid"] = dict(row.detail)
            yield f"data: {json.dumps({'choices': [{'delta': {'content': text[half:]}}]})}\n\n".encode()
            yield b"data: [DONE]\n\n"

        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=chunks())

    jobs.run_pending(factory, manual.worker_settings, httpx.MockTransport(streaming))
    mid = seen["mid"]
    assert mid["state"] == "streaming" and mid["text"] and len(mid["text"]) < 400  # half the reply, live
    assert "KEYS: problem_statement" in mid["prompt"]["system"]  # the exact instructions it was given
    assert "<project_input>" in mid["prompt"]["user"]
    assert manual.step_status(FIRST) == "Awaiting Review"
    with factory() as db:
        done = db.execute(select(AiActivity).where(AiActivity.kind == "model_call", AiActivity.stage_key == FIRST)
                          .order_by(AiActivity.created_at)).scalars().first()
    assert done.detail["state"] == "done" and json.loads(done.detail["text"])["problem_statement"]


def test_a_prompt_that_may_not_fit_the_model_window_is_flagged(manual):  # noqa: F811
    small = manual.worker_settings.model_copy(update={"model_context_tokens": 300})
    manual.start()
    jobs.run_pending(manual.client.app.state.session_factory, small, manual.model.transport())
    with manual.engine.connect() as conn:
        warnings = conn.execute(text("select detail->>'warning' from ai_activity where kind = 'model_call'")).scalars().all()
    assert warnings and all(w and "tokens" in w for w in warnings)


# What each stage is given --------------------------------------------------------------------------------------------

def test_code_generation_reads_the_approved_work_it_needs(env):  # noqa: F811
    _reach_code(env)
    admin = _overseer(env, "org_admin")[0]
    context = next(i for i in _feed(admin, env)["items"] if i["stage"] == CODE and i["kind"] == "context")
    earlier = context["detail"]["earlier_work"]
    assert [w["stage"] for w in earlier][:2] == ["requirements_analysis", "reverse_engineering"]
    assert all(w["reason"] == "needed by this step" for w in earlier)
    assert all(w["included"] and w["chars"] > 0 for w in earlier)


def test_the_budget_is_shared_and_every_cut_is_recorded(env):  # noqa: F811
    from app.projects.models import Project
    from app.workflows import service as engine
    from app.workflows.models import WorkflowExecution, WorkflowVersion

    _reach_code(env)
    with env.client.app.state.session_factory() as db:
        execution = db.execute(select(WorkflowExecution)).scalars().first()
        spec = engine.stage_spec(db.get(WorkflowVersion, execution.workflow_version_id), CODE)
        project = db.get(Project, execution.project_id)
        roomy = engine._work_context(db, execution, project, spec, 1, budget=100_000)
        total = sum(len(u) for u in engine._work_context(db, execution, project, spec, 1, budget=100_000).upstream)
        tight = engine._work_context(db, execution, project, spec, 1, budget=total // 2)
    assert all(i["chars"] == i["full_chars"] for i in roomy.upstream_info)
    assert sum(i["chars"] for i in tight.upstream_info) <= total // 2  # never over the budget
    assert any(i["chars"] < i["full_chars"] or not i["included"] for i in tight.upstream_info)  # and it says so
    assert all(u.endswith("…(cut)") for u, i in zip(tight.upstream, [x for x in tight.upstream_info if x["included"]],
                                                     strict=True) if i["chars"] < i["full_chars"])


def test_a_stage_may_only_read_earlier_stages():
    from app.portal.lifecycle import workflow_spec
    from app.workflows.compiler import CompileError, compile_workflow
    from app.workflows.work import KNOWN_WORK

    spec = workflow_spec("poc")
    first_ai = next(s for s in spec["stages"] if s.get("agent"))
    first_ai["reads"] = ["code_generation"]
    with pytest.raises(CompileError, match="not upstream"):
        compile_workflow(spec, known_work=set(KNOWN_WORK))
