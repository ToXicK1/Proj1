"""Live test against a local Ollama server (OpenAI-compatible endpoint). Runs only when configured.

Set these before running:
    AIDLC_LIVE_OLLAMA_URL=http://127.0.0.1:11434/v1
    AIDLC_LIVE_OLLAMA_MODEL=qwen3-vl:4b-instruct
then:  .venv\\Scripts\\python -m pytest -m live

Without the variables the tests are skipped, so CI stays offline and free.
"""

import os

import pytest

from app.providers.adapters import build_adapter
from app.providers.base import CompletionRequest
from tests.helpers import signup_verify_login
from tests.test_providers_run import _execution, _org_id, _provider, _route, _run, _runs

URL = os.environ.get("AIDLC_LIVE_OLLAMA_URL")
MODEL = os.environ.get("AIDLC_LIVE_OLLAMA_MODEL", "qwen3-vl:4b-instruct")

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not URL, reason="AIDLC_LIVE_OLLAMA_URL not set; live Ollama test skipped"),
]


def test_adapter_gets_a_real_structured_answer_from_ollama():
    adapter = build_adapter("openai_compatible", api_key=None, base_url=URL, app_env="test")
    result = adapter.complete(CompletionRequest(
        system="Reply with one JSON object only. KEYS: summary, assumptions, open_questions",
        user="A remote hiring tool for recruiters.",
        model=MODEL,
        max_tokens=512,
        timeout_seconds=300,
    ))
    assert "summary" in result.text
    assert result.usage.output_tokens > 0


def test_stage_runs_through_the_product_on_the_local_model(client, engine, settings):
    csrf = signup_verify_login(client, engine, "live-ollama@example.com")
    org_id = _org_id(client)
    ollama = _provider(client, csrf, org_id, "ollama-local", "openai_compatible", base_url=URL)
    _route(client, csrf, org_id, "local-drafting", ollama["id"], MODEL)
    execution_id = _execution(client, engine, "local-drafting")

    probe = client.post(f"/api/v1/orgs/{org_id}/providers/{ollama['id']}/health", json={"model": MODEL},
                        headers={"X-CSRF-Token": csrf})
    assert probe.json()["ok"] is True, probe.text

    status, reason = _run(engine, settings, None, execution_id)
    assert status == "AWAITING_HUMAN_REVIEW", reason
    assert _runs(engine, execution_id) == [(1, "succeeded", None, "openai_compatible")]
