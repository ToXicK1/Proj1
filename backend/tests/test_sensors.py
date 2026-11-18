"""Every sensor against passing and failing input. Pure logic: no database."""

import hashlib
import json

import pytest

from app.sensors.registry import (
    SATISFYING,
    SENSORS,
    SensorContext,
    SensorStatus,
    config_problems,
    run_sensor,
    schema_problems,
    stage_references,
)
from app.workflows.compiler import CompileError, compile_workflow
from app.workflows.work import KNOWN_WORK

S = SensorStatus
BRIEF_SENSORS = {
    "required_sections", "json_schema", "requirement_traceability", "missing_dependency", "duplicate_requirements",
    "broken_references", "architecture_consistency", "api_contract", "code_lint", "type_check", "unit_tests",
    "integration_tests", "security_scan", "secret_detection", "dependency_vulnerabilities", "artifact_version",
    "approval_verification",
}


def ctx(content=None, **kw) -> SensorContext:
    content = {} if content is None else content
    sha = hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    base = {"content": content, "artifact_version_id": "v1", "version_number": 1, "stored_sha256": sha,
            "is_current_version": True}
    return SensorContext(**{**base, **kw})


def status(key, config, context):
    assert config_problems(key, config) == []
    return run_sensor(key, config, context).status


def test_every_sensor_named_in_the_brief_exists():
    assert set(SENSORS) == BRIEF_SENSORS


def test_only_pass_and_warning_satisfy_a_mandatory_sensor():
    assert SATISFYING == {S.PASS, S.WARNING}


@pytest.mark.parametrize(
    ("key", "config", "good", "bad"),
    [
        ("required_sections", {"sections": ["goal"]}, {"goal": "x"}, {"goal": ""}),
        ("json_schema", {"json_schema": {"type": "object", "required": ["n"],
                                         "properties": {"n": {"type": "integer", "minimum": 1}}}},
         {"n": 2}, {"n": 0}),
        ("missing_dependency", {"items_key": "items"},
         {"items": [{"id": "a", "depends_on": []}, {"id": "b", "depends_on": ["a"]}]},
         {"items": [{"id": "b", "depends_on": ["a"]}]}),
        ("duplicate_requirements", {"items_key": "items"},
         {"items": [{"id": "a", "text": "x"}, {"id": "b", "text": "y"}]},
         {"items": [{"id": "a", "text": "x"}, {"id": "a", "text": "y"}]}),
        ("broken_references", {"prefixes": ["FR"], "defined_key": "items"},
         {"items": [{"id": "FR-1"}], "note": "see FR-1"}, {"items": [{"id": "FR-1"}], "note": "see FR-2"}),
        ("architecture_consistency", {"components_key": "parts"},
         {"parts": [{"name": "api", "depends_on": ["db"]}, {"name": "db"}]},
         {"parts": [{"name": "api", "depends_on": ["db"]}, {"name": "db", "depends_on": ["api"]}]}),
        ("api_contract", {"endpoints_key": "api"},
         {"api": [{"method": "GET", "path": "/a/{id}", "path_params": ["id"], "responses": {"200": "ok"}}]},
         {"api": [{"method": "GET", "path": "/a/{id}", "responses": {"200": "ok"}}]}),
        ("secret_detection", {}, {"note": "no credentials here"}, {"note": "key sk-abcdefghijklmnop1234"}),
    ],
)
def test_content_sensors_tell_good_from_bad(key, config, good, bad):
    assert status(key, config, ctx(good)) is S.PASS
    assert status(key, config, ctx(bad)) is S.FAIL


def test_traceability_finds_gaps_and_orphans():
    config = {"source_stage": "reqs", "source_key": "items", "links_key": "links"}
    upstream = {"reqs": {"items": [{"id": "R1"}, {"id": "R2"}]}}
    full = {"links": [{"requirement_id": "R1"}, {"requirement_id": "R2"}]}
    assert status("requirement_traceability", config, ctx(full, upstream=upstream)) is S.PASS
    gap = run_sensor("requirement_traceability", config, ctx({"links": [{"requirement_id": "R1"}]}, upstream=upstream))
    assert gap.status is S.FAIL and "R2" in gap.findings[0].description
    orphan = {"links": [*full["links"], {"requirement_id": "R9"}]}
    assert status("requirement_traceability", config, ctx(orphan, upstream=upstream)) is S.FAIL
    assert status("requirement_traceability", config, ctx(full, upstream={"reqs": None})) is S.ERROR


@pytest.mark.parametrize(
    ("key", "kind"),
    [("code_lint", "lint"), ("type_check", "type_check"), ("unit_tests", "unit_tests"),
     ("integration_tests", "integration_tests"), ("security_scan", "security_scan"),
     ("dependency_vulnerabilities", "dependency_audit")],
)
def test_evidence_sensors_ignore_claims_inside_the_artifact(key, kind):
    claim = {key: "PASS", kind: {"outcome": "pass"}, "tests_passed": True}
    assert status(key, {}, ctx(claim)) is S.ERROR
    assert status(key, {}, ctx(claim, evidence={kind: {"outcome": "pass", "findings": []}})) is S.PASS
    assert status(key, {}, ctx(claim, evidence={kind: {"outcome": "fail", "findings": ["3 failed"]}})) is S.FAIL


def test_artifact_version_detects_tampering_and_stale_versions():
    assert status("artifact_version", {}, ctx({"a": 1})) is S.PASS
    assert status("artifact_version", {}, ctx({"a": 1}, stored_sha256="0" * 64)) is S.FAIL
    assert status("artifact_version", {}, ctx({"a": 1}, is_current_version=False)) is S.FAIL


def test_approval_verification_reads_recorded_approvals_only():
    config = {"stages": ["reqs"]}
    assert status("approval_verification", config, ctx({"approved": True})) is S.FAIL
    assert status("approval_verification", config, ctx({}, approved_stages=frozenset({"reqs"}))) is S.PASS


def test_findings_never_repeat_a_secret_value():
    secret = "sk-abcdefghijklmnop1234"
    outcome = run_sensor("secret_detection", {}, ctx({"nested": [{"note": f"token {secret}"}]}))
    assert outcome.status is S.FAIL
    assert secret not in json.dumps([f.__dict__ for f in outcome.findings])
    assert outcome.findings[0].evidence == {"path": "$.nested[0].note", "kind": "api_key"}


def test_missing_input_is_an_error_and_empty_lists_do_not_satisfy():
    assert status("missing_dependency", {"items_key": "items"}, ctx({})) is S.ERROR
    assert status("missing_dependency", {"items_key": "items"}, ctx({"items": "text"})) is S.ERROR
    empty = status("missing_dependency", {"items_key": "items"}, ctx({"items": []}))
    assert empty is S.NOT_APPLICABLE and empty not in SATISFYING


def test_similar_text_is_only_a_warning():
    content = {"items": [{"id": "a", "text": "Same  Text"}, {"id": "b", "text": "same text"}]}
    assert status("duplicate_requirements", {"items_key": "items"}, content and ctx(content)) is S.WARNING


def test_schema_subset_refuses_what_it_cannot_enforce():
    assert schema_problems({"type": "object", "pattern": "x"}) == ["$: unsupported keyword 'pattern'"]
    assert schema_problems({"properties": {"a": {"type": "wat"}}}) == ["$.a: unknown type 'wat'"]
    assert config_problems("json_schema", {"json_schema": {"$ref": "#/x"}})
    assert config_problems("nope", {}) == ["unknown sensor 'nope'"]
    assert config_problems("broken_references", {"prefixes": ["a|b"], "defined_key": "x"})
    assert stage_references("approval_verification", {"stages": ["a"]}) == ["a"]


def _flow(*sensors, depends=()):
    stages = [{"id": "up", "name": "up", "work": "intake_summary"}] if depends else []
    stages.append({"id": "s", "name": "s", "depends_on": list(depends), "work": "intake_summary",
                   "sensors": list(sensors)})
    return {"key": "f", "name": "f", "stages": stages}


@pytest.mark.parametrize(
    ("sensors", "expected"),
    [
        ([{"key": "nope"}], "unknown sensor"),
        ([{"key": "secret_detection"}, {"key": "secret_detection"}], "listed twice"),
        ([{"key": "required_sections", "config": {}}], "sections"),
        ([{"key": "secret_detection", "allow_risk_acceptance": True}], "security sensor"),
        ([{"key": "approval_verification", "config": {"stages": ["other"]}}], "not upstream"),
    ],
)
def test_compiler_refuses_bad_sensor_configuration(sensors, expected):
    with pytest.raises(CompileError) as exc:
        compile_workflow(_flow(*sensors), set(KNOWN_WORK))
    assert any(expected in p for p in exc.value.problems), exc.value.problems


def test_compiler_accepts_a_sensor_that_reads_an_upstream_stage():
    sensor = {"key": "approval_verification", "config": {"stages": ["up"]}}
    assert compile_workflow(_flow(sensor, depends=["up"]), set(KNOWN_WORK)).order == ["up", "s"]
