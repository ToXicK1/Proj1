"""Deterministic sensors. Pure functions: same input, same result. No AI and no database.

A sensor never trusts a claim made inside the artifact it checks. Sensors about code quality, tests
and security therefore read evidence recorded outside the artifact; without it they report ERROR,
which fails closed. The platform does not run linters, tests or scanners itself yet.
"""

import hashlib
import json
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class SensorStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARNING = "WARNING"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    ERROR = "ERROR"


# A mandatory sensor is satisfied only by these. NOT_APPLICABLE does not count: otherwise an artifact
# could dodge a mandatory check by leaving out what the check looks at.
SATISFYING = frozenset({SensorStatus.PASS, SensorStatus.WARNING})


@dataclass(frozen=True)
class SensorContext:
    content: dict[str, Any]
    artifact_version_id: str
    version_number: int
    stored_sha256: str
    is_current_version: bool
    upstream: dict[str, dict[str, Any] | None] = field(default_factory=dict)
    approved_stages: frozenset[str] = frozenset()
    evidence: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class Finding:
    description: str
    evidence: dict[str, Any] = field(default_factory=dict)
    remediation: str = ""


@dataclass(frozen=True)
class Outcome:
    status: SensorStatus
    findings: tuple[Finding, ...] = ()


class MissingInput(Exception):
    """Something the sensor must read is absent. Reported as ERROR, never as a pass."""


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoConfig(_Config):
    pass


class SectionsConfig(_Config):
    sections: list[str] = Field(min_length=1, max_length=50)


class SchemaConfig(_Config):
    json_schema: dict[str, Any]


class TraceConfig(_Config):
    source_stage: str
    source_key: str
    links_key: str
    id_field: str = "id"
    link_field: str = "requirement_id"


class DependencyConfig(_Config):
    items_key: str
    id_field: str = "id"
    depends_field: str = "depends_on"


class DuplicateConfig(_Config):
    items_key: str
    id_field: str = "id"
    text_field: str = "text"


class ReferenceConfig(_Config):
    prefixes: list[str] = Field(min_length=1, max_length=10)
    defined_key: str
    id_field: str = "id"
    source_stage: str | None = None


class ArchitectureConfig(_Config):
    components_key: str
    name_field: str = "name"
    depends_field: str = "depends_on"


class ApiConfig(_Config):
    endpoints_key: str


class ApprovalConfig(_Config):
    stages: list[str] = Field(min_length=1, max_length=50)


def _items(data: dict[str, Any], key: str) -> list[dict[str, Any]]:
    if key not in data:
        raise MissingInput(f"'{key}' is missing")
    value = data[key]
    if not isinstance(value, list) or not all(isinstance(v, dict) for v in value):
        raise MissingInput(f"'{key}' must be a list of objects")
    return value


def _source(ctx: SensorContext, stage: str) -> dict[str, Any]:
    content = ctx.upstream.get(stage)
    if content is None:
        raise MissingInput(f"stage '{stage}' has no artifact")
    return content


def _result(findings: list[Finding], on_problem: SensorStatus = SensorStatus.FAIL) -> Outcome:
    return Outcome(on_problem, tuple(findings)) if findings else Outcome(SensorStatus.PASS)


def required_sections(cfg: SectionsConfig, ctx: SensorContext) -> Outcome:
    empty = (None, "", [], {})
    return _result([
        Finding(f"Required section '{s}' is missing or empty", {"section": s}, f"Add content for '{s}'.")
        for s in cfg.sections if ctx.content.get(s) in empty
    ])


SCHEMA_KEYWORDS = frozenset({
    "type", "required", "properties", "additionalProperties", "items", "enum", "minLength", "maxLength",
    "minItems", "maxItems", "minimum", "maximum",
})
_TYPES: dict[str, tuple[type, ...]] = {
    "object": (dict,), "array": (list,), "string": (str,), "boolean": (bool,),
    "integer": (int,), "number": (int, float), "null": (type(None),),
}


def schema_problems(schema: Any, path: str = "$") -> list[str]:
    """Only a known subset of JSON Schema is accepted, so nothing is silently ignored."""
    if not isinstance(schema, dict):
        return [f"{path}: schema must be an object"]
    problems = [f"{path}: unsupported keyword '{k}'" for k in schema if k not in SCHEMA_KEYWORDS]
    if "type" in schema and schema["type"] not in _TYPES:
        problems.append(f"{path}: unknown type '{schema['type']}'")
    for name, sub in (schema.get("properties") or {}).items():
        problems += schema_problems(sub, f"{path}.{name}")
    if "items" in schema:
        problems += schema_problems(schema["items"], f"{path}[]")
    return problems


def _is_type(value: Any, name: str) -> bool:
    if name in ("integer", "number") and isinstance(value, bool):
        return False
    return isinstance(value, _TYPES[name])


def _validate(value: Any, schema: dict[str, Any], path: str, out: list[Finding]) -> None:
    def problem(text: str) -> None:
        out.append(Finding(f"{path}: {text}", {"path": path}, "Correct the value to match the schema."))

    if "type" in schema and not _is_type(value, schema["type"]):
        problem(f"expected {schema['type']}")
        return
    if "enum" in schema and value not in schema["enum"]:
        problem("value is not one of the allowed values")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            problem("text is too short")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            problem("text is too long")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            problem("value is too small")
        if "maximum" in schema and value > schema["maximum"]:
            problem("value is too large")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            problem("too few items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            problem("too many items")
        if "items" in schema:
            for i, item in enumerate(value):
                _validate(item, schema["items"], f"{path}[{i}]", out)
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for name in schema.get("required", []):
            if name not in value:
                out.append(Finding(f"{path}.{name}: required value is missing", {"path": f"{path}.{name}"},
                                   "Add the required value."))
        for name, item in value.items():
            if name in properties:
                _validate(item, properties[name], f"{path}.{name}", out)
            elif schema.get("additionalProperties") is False:
                out.append(Finding(f"{path}.{name}: value is not allowed", {"path": f"{path}.{name}"},
                                   "Remove the value."))


def json_schema(cfg: SchemaConfig, ctx: SensorContext) -> Outcome:
    findings: list[Finding] = []
    _validate(ctx.content, cfg.json_schema, "$", findings)
    return _result(findings)


def requirement_traceability(cfg: TraceConfig, ctx: SensorContext) -> Outcome:
    required = [i.get(cfg.id_field) for i in _items(_source(ctx, cfg.source_stage), cfg.source_key)]
    if not required:
        return Outcome(SensorStatus.NOT_APPLICABLE)
    linked = [i.get(cfg.link_field) for i in _items(ctx.content, cfg.links_key)]
    findings = [Finding(f"Requirement {r} is not covered", {"requirement": r}, "Link work to this requirement.")
                for r in required if r not in linked]
    findings += [Finding(f"Link points at unknown requirement {r}", {"requirement": r}, "Remove or correct the link.")
                 for r in linked if r not in required]
    return _result(findings)


def missing_dependency(cfg: DependencyConfig, ctx: SensorContext) -> Outcome:
    items = _items(ctx.content, cfg.items_key)
    if not items:
        return Outcome(SensorStatus.NOT_APPLICABLE)
    ids = {i.get(cfg.id_field) for i in items}
    return _result([
        Finding(f"{i.get(cfg.id_field)} depends on unknown item {d}", {"item": i.get(cfg.id_field), "missing": d},
                "Add the missing item or remove the dependency.")
        for i in items for d in i.get(cfg.depends_field) or [] if d not in ids
    ])


def duplicate_requirements(cfg: DuplicateConfig, ctx: SensorContext) -> Outcome:
    items = _items(ctx.content, cfg.items_key)
    if not items:
        return Outcome(SensorStatus.NOT_APPLICABLE)
    ids = Counter(i.get(cfg.id_field) for i in items)
    hard = [Finding(f"Identifier {k} is used {n} times", {"id": k}, "Give each item its own identifier.")
            for k, n in ids.items() if n > 1]
    if hard:
        return Outcome(SensorStatus.FAIL, tuple(hard))
    texts = Counter(" ".join(str(i.get(cfg.text_field, "")).lower().split()) for i in items)
    soft = [Finding("Two items have the same text", {"text_sha256": hashlib.sha256(t.encode()).hexdigest()[:12]},
                    "Merge the items or make them distinct.")
            for t, n in texts.items() if t and n > 1]
    return _result(soft, SensorStatus.WARNING)


def _strings(value: Any, path: str = "$") -> list[tuple[str, str]]:
    if isinstance(value, str):
        return [(path, value)]
    if isinstance(value, list):
        return [s for i, item in enumerate(value) for s in _strings(item, f"{path}[{i}]")]
    if isinstance(value, dict):
        return [s for k, item in value.items() for s in _strings(item, f"{path}.{k}")]
    return []


def broken_references(cfg: ReferenceConfig, ctx: SensorContext) -> Outcome:
    holder = _source(ctx, cfg.source_stage) if cfg.source_stage else ctx.content
    defined = {str(i.get(cfg.id_field)) for i in _items(holder, cfg.defined_key)}
    pattern = re.compile(r"\b(?:" + "|".join(re.escape(p) for p in cfg.prefixes) + r")-\d+\b")
    findings: dict[str, Finding] = {}
    for path, text in _strings(ctx.content):
        for ref in pattern.findall(text):
            if ref not in defined:
                findings.setdefault(ref, Finding(f"Reference {ref} does not exist", {"reference": ref, "path": path},
                                                 "Define the item or correct the reference."))
    return _result(list(findings.values()))


def architecture_consistency(cfg: ArchitectureConfig, ctx: SensorContext) -> Outcome:
    components = _items(ctx.content, cfg.components_key)
    if not components:
        return Outcome(SensorStatus.NOT_APPLICABLE)
    names = Counter(c.get(cfg.name_field) for c in components)
    findings = [Finding(f"Component {n} is defined {k} times", {"component": n}, "Keep one definition.")
                for n, k in names.items() if k > 1]
    graph = {c.get(cfg.name_field): list(c.get(cfg.depends_field) or []) for c in components}
    findings += [Finding(f"{n} depends on unknown component {d}", {"component": n, "missing": d},
                         "Define the component or remove the dependency.")
                 for n, deps in graph.items() for d in deps if d not in graph]
    state: dict[Any, int] = {}

    def visit(node: Any, trail: tuple[Any, ...]) -> tuple[Any, ...] | None:
        state[node] = 1
        for dep in graph.get(node, []):
            if dep not in graph:
                continue
            if state.get(dep) == 1:
                return (*trail, node, dep)
            if dep not in state:
                cycle = visit(dep, (*trail, node))
                if cycle:
                    return cycle
        state[node] = 2
        return None

    for name in graph:
        if name not in state:
            cycle = visit(name, ())
            if cycle:
                findings.append(Finding("Components depend on each other in a cycle", {"cycle": list(cycle)},
                                        "Break the cycle."))
                break
    return _result(findings)


HTTP_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})


def api_contract(cfg: ApiConfig, ctx: SensorContext) -> Outcome:
    endpoints = _items(ctx.content, cfg.endpoints_key)
    if not endpoints:
        return Outcome(SensorStatus.NOT_APPLICABLE)
    findings: list[Finding] = []
    seen: Counter[tuple[str, str]] = Counter()
    for e in endpoints:
        method, path = str(e.get("method", "")).upper(), str(e.get("path", ""))
        label = f"{method or '?'} {path or '?'}"
        seen[(method, path)] += 1
        if method not in HTTP_METHODS:
            findings.append(Finding(f"{label}: unknown HTTP method", {"endpoint": label}, "Use a standard method."))
        if not path.startswith("/"):
            findings.append(Finding(f"{label}: path must start with /", {"endpoint": label}, "Correct the path."))
        if not e.get("responses"):
            findings.append(Finding(f"{label}: no responses are defined", {"endpoint": label}, "Define responses."))
        declared = set(e.get("path_params") or [])
        used = set(re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", path))
        if declared != used:
            findings.append(Finding(f"{label}: path parameters do not match the path", {"endpoint": label},
                                    "Declare exactly the parameters used in the path."))
    findings += [Finding(f"{m} {p} is defined {n} times", {"endpoint": f"{m} {p}"}, "Keep one definition.")
                 for (m, p), n in seen.items() if n > 1]
    return _result(findings)


SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("api_key", re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}\b")),
    ("assigned_secret", re.compile(
        r"(?i)\b(?:password|passwd|secret|api[_-]?key|access[_-]?token)\b\s*[:=]\s*['\"]?[^\s'\"]{12,}")),
)


def secret_detection(_: NoConfig, ctx: SensorContext) -> Outcome:
    """Findings name the location and the kind of secret. They never repeat the value."""
    findings = []
    for path, text in _strings(ctx.content):
        for kind, pattern in SECRET_PATTERNS:
            if pattern.search(text):
                findings.append(Finding(f"Possible {kind} at {path}", {"path": path, "kind": kind},
                                        "Remove the value and rotate it if it was real."))
    return _result(findings)


def artifact_version(_: NoConfig, ctx: SensorContext) -> Outcome:
    actual = hashlib.sha256(json.dumps(ctx.content, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    findings = []
    if actual != ctx.stored_sha256:
        findings.append(Finding("Artifact content does not match its recorded hash",
                                {"artifact_version": ctx.artifact_version_id}, "Treat the version as tampered."))
    if not ctx.is_current_version:
        findings.append(Finding("This is not the current artifact version",
                                {"artifact_version": ctx.artifact_version_id}, "Validate the current version."))
    return _result(findings)


def approval_verification(cfg: ApprovalConfig, ctx: SensorContext) -> Outcome:
    return _result([Finding(f"Stage '{s}' has no valid approval for its current version", {"stage": s},
                            "Obtain the approval first.") for s in cfg.stages if s not in ctx.approved_stages])


def _evidence_sensor(kind: str) -> Callable[[NoConfig, SensorContext], Outcome]:
    def check(_: NoConfig, ctx: SensorContext) -> Outcome:
        record = ctx.evidence.get(kind)
        if record is None:
            raise MissingInput(f"no '{kind}' evidence is recorded for this artifact version")
        if record["outcome"] == "pass":
            return Outcome(SensorStatus.PASS)
        details = record.get("findings") or ["The recorded result was a failure"]
        return Outcome(SensorStatus.FAIL, tuple(
            Finding(str(d), {"evidence": kind}, "Fix the problem and record new evidence.") for d in details))

    return check


@dataclass(frozen=True)
class SensorDefinition:
    key: str
    category: str
    description: str
    config: type[_Config]
    check: Callable[[Any, SensorContext], Outcome]
    version: int = 1
    evidence_kind: str | None = None


def _d(key: str, category: str, description: str, config: type[_Config], check: Callable[..., Outcome],
       evidence_kind: str | None = None) -> SensorDefinition:
    return SensorDefinition(key, category, description, config, check, evidence_kind=evidence_kind)


def _e(key: str, category: str, description: str, kind: str) -> SensorDefinition:
    return _d(key, category, description, NoConfig, _evidence_sensor(kind), kind)


SENSORS: dict[str, SensorDefinition] = {s.key: s for s in (
    _d("required_sections", "document", "Required sections are present and not empty", SectionsConfig, required_sections),
    _d("json_schema", "document", "Content matches a JSON schema", SchemaConfig, json_schema),
    _d("requirement_traceability", "traceability", "Every upstream requirement is covered", TraceConfig,
       requirement_traceability),
    _d("missing_dependency", "traceability", "Every dependency points at a known item", DependencyConfig,
       missing_dependency),
    _d("duplicate_requirements", "document", "Identifiers are unique and texts are distinct", DuplicateConfig,
       duplicate_requirements),
    _d("broken_references", "traceability", "Every cited identifier exists", ReferenceConfig, broken_references),
    _d("architecture_consistency", "architecture", "Components are unique, known and free of cycles",
       ArchitectureConfig, architecture_consistency),
    _d("api_contract", "architecture", "Endpoints are well formed and unique", ApiConfig, api_contract),
    _e("code_builds", "code", "Generated code built in the sandbox", "build"),
    _e("code_lint", "code", "Recorded lint result", "lint"),
    _e("type_check", "code", "Recorded type-check result", "type_check"),
    _e("unit_tests", "test", "Recorded unit test result", "unit_tests"),
    _e("integration_tests", "test", "Recorded integration test result", "integration_tests"),
    _e("security_scan", "security", "Recorded security scan result", "security_scan"),
    _d("secret_detection", "security", "No credentials appear in the artifact", NoConfig, secret_detection),
    _e("dependency_vulnerabilities", "security", "Recorded dependency audit result", "dependency_audit"),
    _d("artifact_version", "integrity", "Content matches its hash and is the current version", NoConfig,
       artifact_version),
    _d("approval_verification", "governance", "Named stages hold a valid approval", ApprovalConfig,
       approval_verification),
)}
EVIDENCE_KINDS: frozenset[str] = frozenset(s.evidence_kind for s in SENSORS.values() if s.evidence_kind)
SANDBOX_ONLY_EVIDENCE = frozenset({"build"})  # only the sandbox itself can report this
SECURITY_EVIDENCE: frozenset[str] = frozenset(
    s.evidence_kind for s in SENSORS.values() if s.evidence_kind and s.category == "security")


def config_problems(key: str, raw: dict[str, Any]) -> list[str]:
    definition = SENSORS.get(key)
    if definition is None:
        return [f"unknown sensor '{key}'"]
    try:
        config = definition.config.model_validate(raw)
    except ValidationError as exc:
        return [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()]
    if isinstance(config, SchemaConfig):
        return schema_problems(config.json_schema)
    if isinstance(config, ReferenceConfig):
        return [f"prefix '{p}' must be 1 to 8 capital letters" for p in config.prefixes
                if not re.fullmatch(r"[A-Z]{1,8}", p)]
    return []


def stage_references(key: str, raw: dict[str, Any]) -> list[str]:
    """Other stages this sensor reads. The compiler requires them to be upstream of the stage."""
    if key in ("requirement_traceability", "broken_references"):
        stage = raw.get("source_stage")
        return [stage] if stage else []
    return list(raw.get("stages", [])) if key == "approval_verification" else []


def run_sensor(key: str, raw_config: dict[str, Any], ctx: SensorContext) -> Outcome:
    definition = SENSORS[key]
    try:
        return definition.check(definition.config.model_validate(raw_config), ctx)
    except MissingInput as exc:
        return Outcome(SensorStatus.ERROR, (Finding(f"Sensor could not run: {exc}", {}, "Provide the missing input."),))
    except Exception as exc:  # noqa: BLE001 - a crashing sensor must fail closed, never pass
        return Outcome(SensorStatus.ERROR, (Finding(f"Sensor failed: {type(exc).__name__}", {}, "Check the input."),))
