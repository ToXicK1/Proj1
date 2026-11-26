"""Phase 1c: the database tool registry mirrors the reviewed definitions, administrators enable or disable tools
(audited), and grants and runs respect it: department authorisation, executor WRITE/EXECUTE tools grantable only to a
department their definition names (Phase 2e), people-only tools never grantable, and a disabled tool refused even to
an agent version that already holds it."""

import uuid
from dataclasses import replace

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.agents import tool_runtime
from app.tools import definitions, registry
from tests.test_meetings import managed, s3  # noqa: F401  (fixtures)
from tests.test_pm import _setup, _signed_in

AGENT = {"key": "ba-helper", "kind": "lead", "profile": "business_analyst", "instructions": "Help the BA.",
         "required_keys": ["answer"], "model_route": "default", "context_sources": ["project_input"]}


def test_the_registry_mirrors_every_reviewed_definition_and_versions_changes(engine, monkeypatch):
    with Session(engine) as db:
        registry.sync(db)
        db.commit()
        entries = {e.key: e for e in db.query(registry.ToolRegistryEntry)}
        assert set(entries) == set(definitions.DEFINITIONS)
        assert entries["run_checks"].definition["executor_kind"] == "checks"
        assert entries["read_project"].health == "ok" and registry.health_of(entries["repo_read"]) == "unavailable"
        assert registry.sync(db) == []  # nothing changed, nothing written
        changed = replace(definitions.DEFINITIONS["repo_read"], description="Something else")
        monkeypatch.setitem(definitions.DEFINITIONS, "repo_read", changed)
        with pytest.raises(RuntimeError):
            registry.sync(db)  # a definition may not change without a new version
        monkeypatch.setitem(definitions.DEFINITIONS, "repo_read", replace(changed, version=2))
        assert registry.sync(db) == ["repo_read"]
        db.commit()
        versions = [v for v, in db.execute(text("select version from tool_registry_versions where key = 'repo_read' "
                                                "order by version"))]
        assert versions == [1, 2]  # what the tool was stays on record
        registry.report_executor_alive(db)
        assert registry.health_of(db.get(registry.ToolRegistryEntry, "repo_read")) == "ok"


def test_administrators_switch_tools_and_grants_follow_the_registry(managed, engine):  # noqa: F811
    c, h, org, _, people = _setup(managed, engine)
    with Session(engine) as db:
        registry.sync(db)
        db.commit()
    url = f"/api/v1/orgs/{org}/tool-registry"
    analyst, ah = _signed_in(managed, people["analyst"])
    listed = {t["key"]: t for t in analyst.get(url).json()["items"]}
    assert listed["read_project"]["grantable"] and listed["run_checks"]["grantable"]  # Phase 2e: for code departments
    assert listed["merge_change_set"]["departments"] == [] and not listed["merge_change_set"]["grantable"]
    assert analyst.put(f"{url}/read_project", headers=ah, json={"enabled": False}).status_code == 403

    agents = f"/api/v1/orgs/{org}/agents"
    write_tool = c.post(agents, headers=h, json={**AGENT, "tools": ["repo_commit"]})  # the BA is not a code department
    assert write_tool.status_code == 422 and "not authorised" in write_tool.text
    people_only = c.post(agents, headers=h, json={**AGENT, "tools": ["merge_change_set"]})
    assert people_only.status_code == 422 and "cannot be granted" in people_only.text
    held = c.post(agents, headers=h, json={**AGENT, "tools": ["read_project"]})
    assert held.status_code == 201, held.text
    off = c.put(f"{url}/read_project", headers=h, json={"enabled": False})
    assert off.status_code == 200 and off.json()["enabled"] is False and not off.json()["grantable"]
    refused = c.post(agents, headers=h, json={**AGENT, "key": "ba-helper-2", "tools": ["read_project"]})
    assert refused.status_code == 422 and "disabled" in refused.text
    with Session(engine) as db:
        scope = tool_runtime.ToolScope(db=db, stage_execution_id=uuid.uuid4(), grants=("read_project",))
        result = tool_runtime.execute(scope, "read_project", "{}")
        assert result.status == "refused" and "disabled" in result.summary  # the old grant does not override it
        events = list(db.execute(text("select payload from audit_events where event_type = 'tool_registry.changed'"
                                      )).scalars())
    assert [{k: e[k] for k in ("tool", "version", "enabled", "previous")} for e in events] == [
        {"tool": "read_project", "version": 1, "enabled": False, "previous": True}]
    assert events[0]["correlation_id"]  # tied to the request that made the change


def test_department_authorisation(managed, engine):  # noqa: F811
    from app.agents.tools import grant_problems

    assert grant_problems(["read_project"], "project_manager") == []  # "*": every department
    assert "not authorised" in grant_problems(["repo_commit"], "business_analyst")[0] or \
        "cannot be granted" in grant_problems(["repo_commit"], "business_analyst")[0]
    assert "cannot be granted" in grant_problems(["merge_change_set"], "software_developer")[0]
