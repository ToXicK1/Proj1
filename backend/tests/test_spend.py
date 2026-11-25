"""Spend controls: the Claude adapter's caching, thinking and tools; error classification; paused providers;
budgets; cheapest-first routing; and the administrator APIs.

Vendor HTTP is mocked (httpx.MockTransport). These prove our requests follow Anthropic's documented shapes and that
the platform reacts correctly to documented failures; they do not prove a live vendor accepts them.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.notifications.models import Notification
from app.providers import costs
from app.providers.adapters import build_adapter, http_error
from app.providers.base import CompletionRequest, ProviderError
from app.providers.models import AiProvider, ModelPrice, SpendBudget, TokenUsage
from tests.helpers import signup_verify_login
from tests.test_providers_run import (
    GOOD,
    Scripted,
    _execution,
    _lazy,
    _openai,
    _org_id,
    _provider,
    _route,
    _run,
    _runs,
)

REQ = CompletionRequest(system="Reply with JSON. KEYS: summary", user="hello", model="claude-sonnet-5-5",
                        max_tokens=1024)


def _claude(transport):
    return build_adapter("anthropic", api_key="sk-test-1234567890", base_url=None, transport=transport,
                         app_env="test")


def _capture(response: httpx.Response, seen: list):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return response
    return httpx.MockTransport(handler)


def _anthropic_ok(text_out: str = GOOD, usage=None) -> httpx.Response:
    return httpx.Response(200, json={"model": "claude-sonnet-5-5", "stop_reason": "end_turn",
                                     "content": [{"type": "thinking", "thinking": "Weighing it.", "signature": "s"},
                                                 {"type": "text", "text": text_out}],
                                     "usage": usage or {"input_tokens": 100, "output_tokens": 50,
                                                        "cache_read_input_tokens": 900,
                                                        "cache_creation_input_tokens": 0}})


# --- the Claude adapter --------------------------------------------------------------------------------------------

def test_claude_caches_instructions_and_uses_adaptive_thinking_on_current_models():
    seen: list = []
    result = _claude(_capture(_anthropic_ok(), seen)).complete(REQ)
    body = json.loads(seen[0].content)
    assert body["system"] == [{"type": "text", "text": REQ.system, "cache_control": {"type": "ephemeral"}}]
    assert body["cache_control"] == {"type": "ephemeral"}
    assert body["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert "temperature" not in body and "budget_tokens" not in json.dumps(body)
    assert body["max_tokens"] >= 16000  # reasoning shares the output budget
    assert result.thinking == "Weighing it." and json.loads(result.text)["summary"]
    assert (result.usage.cache_read_tokens, result.usage.cache_write_tokens) == (900, 0)


def test_claude_older_models_keep_temperature_and_no_thinking():
    seen: list = []
    _claude(_capture(_anthropic_ok(), seen)).complete(CompletionRequest(
        system="s", user="u", model="claude-3-haiku", max_tokens=64))
    body = json.loads(seen[0].content)
    assert "thinking" not in body and body["temperature"] == 0.0 and body["max_tokens"] == 64


def test_claude_tool_calls_come_back_and_are_replayed_in_claude_shape():
    blocks = [{"type": "thinking", "thinking": "Need the brief.", "signature": "sig"},
              {"type": "tool_use", "id": "toolu_1", "name": "read_project", "input": {}}]
    seen: list = []
    tool = {"type": "function", "function": {"name": "read_project", "description": "Read it",
                                             "parameters": {"type": "object", "properties": {}}}}
    first = _claude(_capture(httpx.Response(200, json={
        "model": "claude-sonnet-5-5", "stop_reason": "tool_use", "content": blocks,
        "usage": {"input_tokens": 5, "output_tokens": 5}}), seen)).complete(
        CompletionRequest(system="s", user="u", model="claude-sonnet-5-5", tools=(tool,)))
    assert json.loads(seen[0].content)["tools"] == [
        {"name": "read_project", "description": "Read it", "input_schema": {"type": "object", "properties": {}}}]
    assert first.tool_calls == ({"id": "toolu_1", "name": "read_project", "arguments": "{}"},)
    assert first.native_content == tuple(blocks)

    conversation = (
        {"role": "system", "content": "s"}, {"role": "user", "content": "u"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "toolu_1", "type": "function",
                                                             "function": {"name": "read_project", "arguments": "{}"}}],
         "_native_anthropic": blocks},
        {"role": "tool", "tool_call_id": "toolu_1", "content": "the brief"},
    )
    seen2: list = []
    _claude(_capture(_anthropic_ok(), seen2)).complete(
        CompletionRequest(system="s", user="u", model="claude-sonnet-5-5", messages=conversation, tools=(tool,)))
    sent = json.loads(seen2[0].content)["messages"]
    assert sent[1] == {"role": "assistant", "content": blocks}  # thinking signature preserved for the API
    assert sent[2] == {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_1",
                                                     "content": "the brief"}]}


def test_claude_streams_thinking_text_and_tool_arguments():
    events = [
        {"type": "message_start", "message": {"model": "claude-sonnet-5-5", "usage": {"input_tokens": 20,
                                                                                    "cache_read_input_tokens": 400}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "Hmm."}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "signature_delta", "signature": "sg"}},
        {"type": "content_block_stop", "index": 0},
        {"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "t1",
                                                                      "name": "search_approved_work"}},
        {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": '{"qu'}},
        {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta",
                                                              "partial_json": 'ery": "tips"}'}},
        {"type": "content_block_stop", "index": 1},
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 30}},
        {"type": "message_stop"},
    ]
    stream = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events)
    deltas: list = []
    result = _claude(httpx.MockTransport(lambda r: httpx.Response(
        200, headers={"content-type": "text/event-stream"}, content=stream.encode()))).complete(
        CompletionRequest(system="s", user="u", model="claude-sonnet-5-5",
                          on_delta=lambda kind, text: deltas.append((kind, text))))
    assert deltas == [("thinking", "Hmm.")]
    assert result.tool_calls == ({"id": "t1", "name": "search_approved_work", "arguments": '{"query": "tips"}'},)
    assert result.native_content[0]["signature"] == "sg"
    assert (result.usage.input_tokens, result.usage.output_tokens, result.usage.cache_read_tokens) == (20, 30, 400)


def test_claude_refusal_is_content_filtered():
    response = httpx.Response(200, json={"model": "m", "stop_reason": "refusal", "content": [],
                                         "usage": {"input_tokens": 1, "output_tokens": 0}})
    try:
        _claude(httpx.MockTransport(lambda r: response)).complete(REQ)
        raise AssertionError("expected a refusal")
    except ProviderError as exc:
        assert exc.kind == "content_filtered"


def test_out_of_credit_and_spend_caps_are_told_apart_from_rate_limits():
    cases = [
        (402, {"type": "error", "error": {"type": "billing_error", "message": "Add credit"}}, {}, "quota_exhausted"),
        (429, {"type": "error", "error": {"type": "rate_limit_error", "message": "enforced_spend_limit_reached"}}, {},
         "quota_exhausted"),
        (429, {"error": {"code": "insufficient_quota", "message": "You exceeded your current quota"}}, {},
         "quota_exhausted"),
        (429, {"type": "error", "error": {"type": "rate_limit_error", "message": "slow down"}}, {"retry-after": "7"},
         "rate_limited"),
        (529, {"type": "error", "error": {"type": "overloaded_error"}}, {}, "unavailable"),
        (401, {"type": "error", "error": {"type": "authentication_error"}}, {}, "auth"),
    ]
    for status, body, headers, kind in cases:
        error = http_error(httpx.Response(status, json=body, headers=headers))
        assert error.kind == kind, (status, body)
    assert http_error(httpx.Response(429, json={}, headers={"retry-after": "7"})).retry_after == 7.0


# --- money -----------------------------------------------------------------------------------------------------------

def test_prices_include_cache_and_unknown_models_have_no_price():
    price = costs._from_usd(*costs.DEFAULT_PRICES_USD[("anthropic", "claude-sonnet-5-5")], "default")
    # 1M uncached input at $2, 1M output at $10, 1M cache reads at $0.20, 1M cache writes at $2.50
    assert price.cost(1_000_000, 1_000_000, 1_000_000, 1_000_000) == 14_700_000
    assert costs.pause_for("bad_response", None) is None
    until, reason = costs.pause_for("quota_exhausted", None, datetime(2026, 11, 23, tzinfo=UTC))
    assert until == datetime(2026, 12, 1, tzinfo=UTC) and "credit" in reason
    until, _ = costs.pause_for("rate_limited", 7.0, datetime(2026, 11, 23, tzinfo=UTC))
    assert until == datetime(2026, 11, 23, 0, 0, 7, tzinfo=UTC)
    assert costs.next_month_start(datetime(2026, 12, 15, tzinfo=UTC)) == datetime(2027, 1, 1, tzinfo=UTC)


def _anthropic_json(text_out: str = GOOD) -> httpx.Response:
    return _anthropic_ok(text_out, {"input_tokens": 1000, "output_tokens": 500, "cache_read_input_tokens": 2000,
                                    "cache_creation_input_tokens": 400})


def test_a_claude_run_records_its_cost_from_the_published_price(client, engine, settings):
    csrf = signup_verify_login(client, engine, "spend-cost@example.com")
    org_id = _org_id(client)
    anth = _provider(client, csrf, org_id, "claude", "anthropic", api_key="sk-cost-value-0101")
    _route(client, csrf, org_id, "claude-route", anth["id"], "claude-sonnet-5-5")
    execution_id = _execution(client, engine, "claude-route")
    assert _run(engine, settings, Scripted(anthropic=[_anthropic_json]).transport(), execution_id)[0] \
        == "AWAITING_HUMAN_REVIEW"
    with Session(engine) as s:
        usage = s.execute(select(TokenUsage)).scalars().one()
    # $2/M input, $10/M output, $0.20/M cache read, $2.50/M cache write:
    # 1000*2 + 500*10 + 2000*0.2 + 400*2.5 = 2000 + 5000 + 400 + 1000 = 8400 micro-dollars
    assert (usage.cache_read_tokens, usage.cache_write_tokens, usage.cost_micro_usd) == (2000, 400, 8400)


def test_out_of_credit_pauses_the_provider_and_later_runs_skip_it(client, engine, settings):
    csrf = signup_verify_login(client, engine, "spend-pause@example.com")
    org_id = _org_id(client)
    anth = _provider(client, csrf, org_id, "claude-broke", "anthropic", api_key="sk-pause-value-0102")
    oai = _provider(client, csrf, org_id, "oai-backup", "openai", api_key="sk-pause-value-0103")
    _route(client, csrf, org_id, "pause-route", anth["id"], "claude-sonnet-5-5",
           fallbacks=[{"provider_id": oai["id"], "model": "gpt-x"}])
    broke = httpx.Response(400, json={"type": "error", "error": {
        "type": "invalid_request_error", "message": "Your credit balance is too low"}})
    script = Scripted(anthropic=[lambda: broke], openai=[_lazy(_openai, GOOD)])
    first = _execution(client, engine, "pause-route")
    assert _run(engine, settings, script.transport(), first)[0] == "AWAITING_HUMAN_REVIEW"
    assert len(script.calls["anthropic"]) == 1  # not retried: retrying cannot help
    assert _runs(engine, first) == [(1, "failed", "quota_exhausted", "anthropic"), (2, "succeeded", None, "openai")]
    with Session(engine) as s:
        row = s.get(AiProvider, uuid.UUID(anth["id"]))
        assert row.paused_until >= costs.next_month_start() - timedelta(seconds=1)

    second = _execution(client, engine, "pause-route")
    assert _run(engine, settings, script.transport(), second)[0] == "AWAITING_HUMAN_REVIEW"
    assert len(script.calls["anthropic"]) == 1  # skipped, not called again
    listed = client.get(f"/api/v1/orgs/{org_id}/spend").json()
    paused = next(p for p in listed["providers"] if p["id"] == anth["id"])
    assert paused["paused"] and "credit" in paused["paused_reason"]
    # Every amount is a JSON number: SQL sums are Decimals, which once arrived as text and broke the Spend panel.
    assert listed["by_model"] and listed["by_project"]
    amounts = [listed["spent_usd"], *(m["spent_usd"] for m in listed["by_model"]),
               *(p["spent_usd"] for p in listed["by_project"])]
    assert all(isinstance(a, (int, float)) and not isinstance(a, bool) for a in amounts), amounts

    r = client.post(f"/api/v1/orgs/{org_id}/providers/{anth['id']}/resume", headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200 and r.json()["paused"] is False
    third = _execution(client, engine, "pause-route")
    _run(engine, settings, Scripted(anthropic=[_anthropic_json]).transport(), third)
    assert _runs(engine, third) == [(1, "succeeded", None, "anthropic")]


def test_a_rate_limited_provider_cools_down_briefly(client, engine, settings):
    csrf = signup_verify_login(client, engine, "spend-cool@example.com")
    org_id = _org_id(client)
    anth = _provider(client, csrf, org_id, "claude-busy", "anthropic", api_key="sk-cool-value-0104")
    oai = _provider(client, csrf, org_id, "oai-cool", "openai", api_key="sk-cool-value-0105")
    _route(client, csrf, org_id, "cool-route", anth["id"], "claude-sonnet-5-5",
           fallbacks=[{"provider_id": oai["id"], "model": "gpt-x"}])
    busy = httpx.Response(429, json={"type": "error", "error": {"type": "rate_limit_error"}},
                          headers={"retry-after": "20"})
    execution_id = _execution(client, engine, "cool-route")
    _run(engine, settings, Scripted(anthropic=[lambda: busy], openai=[_lazy(_openai, GOOD)]).transport(),
         execution_id)
    with Session(engine) as s:
        until = s.get(AiProvider, uuid.UUID(anth["id"])).paused_until
    assert timedelta(seconds=5) < until - datetime.now(UTC) <= timedelta(seconds=21)


def _budget(client, csrf, org_id, **body):
    r = client.put(f"/api/v1/orgs/{org_id}/spend-budgets", json=body, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200, r.text
    return r.json()


def _spend_some(engine, org_id: str, micro: int):
    """Records past spend directly: a completed run that cost this much this month."""
    from app.core.db import uuid7
    from app.providers.models import AgentRun

    with Session(engine) as s:
        provider = s.execute(select(AiProvider).where(AiProvider.organization_id == uuid.UUID(org_id))).scalars().first()
        stage_run = s.execute(select(AgentRun).where(AgentRun.organization_id == uuid.UUID(org_id))).scalars().first()
        run = AgentRun(id=uuid7(), organization_id=uuid.UUID(org_id), project_id=stage_run.project_id,
                       stage_execution_id=stage_run.stage_execution_id, route_key="x", provider_id=provider.id,
                       adapter_type=provider.adapter_type, model="claude-sonnet-5-5", attempt=99,
                       status="succeeded", latency_ms=1, kind="lead")
        s.add(run)
        s.flush()
        s.add(TokenUsage(agent_run_id=run.id, input_tokens=1, output_tokens=1, cost_micro_usd=micro))
        s.commit()


def test_a_paused_budget_stops_ai_work_and_tells_the_admins_once(client, engine, settings):
    csrf = signup_verify_login(client, engine, "spend-budget@example.com")
    org_id = _org_id(client)
    anth = _provider(client, csrf, org_id, "claude-b", "anthropic", api_key="sk-budget-value-0106")
    _route(client, csrf, org_id, "budget-route", anth["id"], "claude-sonnet-5-5")
    first = _execution(client, engine, "budget-route")
    _run(engine, settings, Scripted(anthropic=[_anthropic_json]).transport(), first)
    summary = _budget(client, csrf, org_id, limit_usd=1.0, warn_percent=50, on_limit="pause")
    assert summary["budgets"][0]["over"] is False
    _spend_some(engine, org_id, 1_000_000)  # one dollar: at the limit

    script = Scripted(anthropic=[_anthropic_json])
    for _ in range(2):
        execution_id = _execution(client, engine, "budget-route")
        status, reason = _run(engine, settings, script.transport(), execution_id)
        assert status == "FAILED" and "budget_exhausted" in (reason or "")
    assert script.calls["anthropic"] == []  # no paid call was made
    with Session(engine) as s:
        notes = s.execute(select(Notification.kind).where(Notification.kind.like("budget_%"))).scalars().all()
    assert len([n for n in notes if n.startswith("budget_reached")]) == 1  # once a month, not every run


def test_a_free_only_budget_keeps_going_on_the_local_model(client, engine, settings):
    csrf = signup_verify_login(client, engine, "spend-free@example.com")
    org_id = _org_id(client)
    anth = _provider(client, csrf, org_id, "claude-f", "anthropic", api_key="sk-free-value-0107")
    local = _provider(client, csrf, org_id, "local", "openai_compatible", base_url="https://ollama.test/v1")
    _route(client, csrf, org_id, "free-route", anth["id"], "claude-sonnet-5-5",
           fallbacks=[{"provider_id": local["id"], "model": "qwen-local"}])
    first = _execution(client, engine, "free-route")
    _run(engine, settings, Scripted(anthropic=[_anthropic_json]).transport(), first)
    _budget(client, csrf, org_id, limit_usd=0.01, on_limit="free_only")
    _spend_some(engine, org_id, 20_000)

    def local_ok():
        return _openai(GOOD)
    script = Scripted(anthropic=[_anthropic_json], **{"ollama.test": [local_ok]})
    execution_id = _execution(client, engine, "free-route")
    assert _run(engine, settings, script.transport(), execution_id)[0] == "AWAITING_HUMAN_REVIEW"
    assert script.calls["anthropic"] == []
    assert [r[3] for r in _runs(engine, execution_id)] == ["openai_compatible"]


def test_cheapest_first_tries_the_cheaper_model_before_the_primary(client, engine, settings):
    csrf = signup_verify_login(client, engine, "spend-cheap@example.com")
    org_id = _org_id(client)
    anth = _provider(client, csrf, org_id, "claude-c", "anthropic", api_key="sk-cheap-value-0108")
    route = _route(client, csrf, org_id, "cheap-route", anth["id"], "claude-opus-5-5",
                   fallbacks=[{"provider_id": anth["id"], "model": "claude-haiku-5-5"}])
    assert route["strategy"] == "ordered"
    r = client.patch(f"/api/v1/orgs/{org_id}/model-routes/{route['id']}", json={"strategy": "cheapest"},
                     headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200 and r.json()["strategy"] == "cheapest"
    script = Scripted(anthropic=[_anthropic_json])
    execution_id = _execution(client, engine, "cheap-route")
    _run(engine, settings, script.transport(), execution_id)
    assert json.loads(script.calls["anthropic"][0].content)["model"] == "claude-haiku-5-5"


def test_only_admins_see_or_change_money(client, engine):
    from fastapi.testclient import TestClient

    from app.core.db import uuid7
    from app.organizations.models import Membership
    from tests.test_approvals import _user_id

    signup_verify_login(client, engine, "spend-owner@example.com")
    org_id = _org_id(client)
    with TestClient(client.app) as member:
        member_csrf = signup_verify_login(member, engine, "spend-member@example.com", name="Member")
        with Session(engine) as s:
            s.add(Membership(id=uuid7(), organization_id=uuid.UUID(org_id),
                             user_id=_user_id(engine, "spend-member@example.com"), role="member"))
            s.commit()
        headers = {"X-CSRF-Token": member_csrf}
        assert member.get(f"/api/v1/orgs/{org_id}/spend").status_code == 403
        assert member.put(f"/api/v1/orgs/{org_id}/spend-budgets", json={"limit_usd": 1000},
                          headers=headers).status_code == 403
        assert member.put(f"/api/v1/orgs/{org_id}/model-prices", json={
            "adapter_type": "openai", "model": "m", "input_usd_per_mtok": 0, "output_usd_per_mtok": 0},
            headers=headers).status_code == 403
    with TestClient(client.app) as stranger:
        signup_verify_login(stranger, engine, "spend-stranger@example.com", name="Stranger")
        assert stranger.get(f"/api/v1/orgs/{org_id}/spend").status_code in (403, 404)


def test_admin_price_overrides_and_audit(client, engine):
    csrf = signup_verify_login(client, engine, "spend-price@example.com")
    org_id = _org_id(client)
    r = client.put(f"/api/v1/orgs/{org_id}/model-prices", json={
        "adapter_type": "openai", "model": "gpt-x", "input_usd_per_mtok": 1.25, "output_usd_per_mtok": 10},
        headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200, r.text
    mine = next(p for p in r.json()["items"] if p["model"] == "gpt-x")
    assert mine["source"] == "organization" and mine["cache_read_usd_per_mtok"] == 0.125
    assert any(p["model"] == "claude-sonnet-5-5" and p["source"] == "default" for p in r.json()["items"])
    bad = client.put(f"/api/v1/orgs/{org_id}/model-prices", json={
        "adapter_type": "openai", "model": "gpt-x", "input_usd_per_mtok": -1, "output_usd_per_mtok": 1},
        headers={"X-CSRF-Token": csrf})
    assert bad.status_code == 422
    r = client.delete(f"/api/v1/orgs/{org_id}/model-prices/{mine['id']}", headers={"X-CSRF-Token": csrf})
    assert not any(p["model"] == "gpt-x" for p in r.json()["items"])
    with Session(engine) as s:
        assert s.execute(select(ModelPrice)).scalars().all() == []
    assert client.put(f"/api/v1/orgs/{org_id}/spend-budgets", json={"limit_usd": 5},
                      headers={}).status_code in (401, 403)  # CSRF required
    _budget(client, csrf, org_id, limit_usd=5)
    _budget(client, csrf, org_id, limit_usd=7)  # replaces, never a second organization budget
    with Session(engine) as s:
        rows = s.execute(select(SpendBudget)).scalars().all()
    assert [r.monthly_limit_micro_usd for r in rows] == [7_000_000]


def test_a_cooldown_does_not_block_a_route_with_no_other_provider(client, engine, settings):
    csrf = signup_verify_login(client, engine, "spend-only@example.com")
    org_id = _org_id(client)
    anth = _provider(client, csrf, org_id, "claude-only", "anthropic", api_key="sk-only-value-0109")
    _route(client, csrf, org_id, "only-route", anth["id"], "claude-sonnet-5-5")
    down = httpx.Response(529, json={"type": "error", "error": {"type": "overloaded_error"}})
    first = _execution(client, engine, "only-route")
    assert _run(engine, settings, Scripted(anthropic=[lambda: down]).transport(), first) == \
        ("FAILED", "provider failed: unavailable")
    second = _execution(client, engine, "only-route")  # still within the cooldown, but there is nothing else
    assert _run(engine, settings, Scripted(anthropic=[_anthropic_json]).transport(), second)[0] \
        == "AWAITING_HUMAN_REVIEW"
