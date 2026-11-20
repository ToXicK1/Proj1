"""Workflow definition compiler (WORKFLOW_ENGINE.md section 4).

A definition is compiled before it can be stored or executed. Invalid definitions never run.
Compilation returns every problem found, not just the first, with a path to the offending field.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.approvals.policy import PolicyError, parse_policy
from app.sensors.registry import SENSORS, config_problems, stage_references
from app.workflows import conditions

ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
SUPPORTED_EXECUTION = {"sequential", "parallel"}  # parallel: independent branches may run at the same time


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SensorSpec(_Strict):
    key: str
    mandatory: bool = True
    severity: Literal["critical", "high", "medium", "low"] | None = None
    allow_risk_acceptance: bool = False
    config: dict[str, Any] = Field(default_factory=dict)


class StageSpec(_Strict):
    id: str
    name: str = Field(min_length=1, max_length=120)
    depends_on: list[str] = Field(default_factory=list)
    protected: bool = False
    owner_visible: bool = False  # the project owner may see this stage's deliverable
    human_gate: bool = True  # only deterministic work may run without a human decision
    sandbox: bool = False  # build and test generated files in the sandbox before the gate
    sandbox_source: str | None = None  # test the files from this earlier stage instead of this stage's own
    approval_policy: dict[str, Any] | None = None
    work: str = Field(min_length=1, max_length=64)
    output_required_keys: list[str] = Field(default_factory=list)
    condition: dict[str, Any] | None = None  # see app/workflows/conditions.py; false means the stage is skipped
    mandatory: bool = False  # governance steps that may never be skipped, so they cannot carry a condition
    model_route: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_\-]{1,63}$")
    profile: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_\-]{1,63}$")
    agent: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_\-]{1,63}$")
    reviewer: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_\-]{1,63}$")
    sensors: list[SensorSpec] = Field(default_factory=list, max_length=30)
    reads: list[str] = Field(default_factory=list, max_length=20)  # earlier stages whose approved work it needs
    # Support specialists that contribute advisory notes before the lead works (each recorded on its own)
    specialists: list[str] = Field(default_factory=list, max_length=3)


class WorkflowSpec(_Strict):
    key: str
    name: str = Field(min_length=1, max_length=120)
    execution: str = "sequential"
    stages: list[StageSpec] = Field(min_length=1)


class CompileError(Exception):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass
class CompiledWorkflow:
    spec: dict[str, Any]
    graph: dict[str, list[str]]  # stage id -> dependency ids
    order: list[str]  # topological order
    roots: list[str]
    sha256: str = ""
    problems: list[str] = field(default_factory=list)


def _canonical_sha(spec: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(spec, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def compile_workflow(raw: dict[str, Any], known_work: set[str]) -> CompiledWorkflow:
    try:
        spec = WorkflowSpec.model_validate(raw)
    except ValidationError as exc:
        problems = [
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
        ]
        raise CompileError(problems) from exc

    problems: list[str] = []
    if spec.execution not in SUPPORTED_EXECUTION:
        problems.append(f"execution: '{spec.execution}' is not supported (supported: sequential, parallel)")

    ids = [s.id for s in spec.stages]
    seen: set[str] = set()
    for i, stage in enumerate(spec.stages):
        path = f"stages[{i}]"
        if not ID_PATTERN.match(stage.id):
            problems.append(f"{path}.id: '{stage.id}' must be lowercase snake_case")
        if stage.id in seen:
            problems.append(f"{path}.id: duplicate stage id '{stage.id}'")
        seen.add(stage.id)
        if stage.id in stage.depends_on:
            problems.append(f"{path}.depends_on: stage '{stage.id}' depends on itself")
        for dep in stage.depends_on:
            if dep not in ids:
                problems.append(f"{path}.depends_on: unknown stage '{dep}'")
        if stage.work not in known_work:
            problems.append(f"{path}.work: unknown work function '{stage.work}'")
        if stage.approval_policy is not None:
            if stage.approval_policy.get("type") == "conditional":
                problems.append(f"{path}.approval_policy: conditional policies are not supported yet")
            else:
                try:
                    parse_policy(stage.approval_policy)
                except PolicyError as exc:
                    problems.extend(f"{path}.approval_policy.{p}" for p in exc.problems)
        is_ai = stage.work.startswith("ai:")
        if is_ai and stage.agent is None and not stage.model_route:
            problems.append(f"{path}.model_route: AI task '{stage.work}' needs a model route")
        if stage.model_route and not is_ai:
            problems.append(f"{path}.model_route: only AI tasks use a model route")
        if stage.agent is not None:
            if not is_ai:
                problems.append(f"{path}.agent: an agent needs an AI task")
            if stage.model_route:
                problems.append(f"{path}.model_route: an agent carries its own route; remove model_route")
        if stage.reviewer is not None:
            if stage.agent is None:
                problems.append(f"{path}.reviewer: a reviewer needs a lead agent")
            elif stage.reviewer == stage.agent:
                problems.append(f"{path}.reviewer: the reviewer must not be the lead agent")
        if stage.specialists:
            if stage.agent is None:
                problems.append(f"{path}.specialists: specialists support a lead agent; this stage has none")
            for key in stage.specialists:
                if not re.match(r"^[a-z][a-z0-9_\-]{1,63}$", key):
                    problems.append(f"{path}.specialists: '{key}' is not a valid agent key")
                elif key in (stage.agent, stage.reviewer):
                    problems.append(f"{path}.specialists: '{key}' is already this stage's lead or reviewer")
            if len(set(stage.specialists)) != len(stage.specialists):
                problems.append(f"{path}.specialists: each specialist once")
        if stage.sandbox and not is_ai:
            problems.append(f"{path}.sandbox: only AI-generated work is sent to the sandbox")
        if stage.sandbox_source and not stage.sandbox:
            problems.append(f"{path}.sandbox_source: this needs sandbox to be on")
        if not stage.human_gate and is_ai:
            problems.append(f"{path}.human_gate: AI output always needs a human decision")

    graph = {s.id: [d for d in s.depends_on if d in ids] for s in spec.stages}
    for i, stage in enumerate(spec.stages):
        problems += _sensor_problems(f"stages[{i}].sensors", stage, graph)
        if stage.sandbox_source and stage.sandbox_source not in _upstream(stage.id, graph):
            problems.append(f"stages[{i}].sandbox_source: stage '{stage.sandbox_source}' is not upstream")
        if stage.condition is not None:
            if stage.mandatory:
                problems.append(f"stages[{i}].condition: a mandatory stage can never be skipped, so it cannot be conditional")
            if stage.sandbox:
                problems.append(f"stages[{i}].condition: a stage whose code is built and tested cannot be skipped")
            problems += conditions.problems(stage.condition, _upstream(stage.id, graph), f"stages[{i}].condition")
        for ref in stage.reads:
            if ref not in _upstream(stage.id, graph):
                problems.append(f"stages[{i}].reads: stage '{ref}' is not upstream, so its work cannot exist yet")
    order: list[str] = []
    if not problems:
        order, cycle = _topological(graph)
        if cycle:
            problems.append(f"depends_on: circular dependency through {' -> '.join(cycle)}")

    if problems:
        raise CompileError(problems)

    roots = [s for s in ids if not graph[s]]
    compiled_spec = spec.model_dump()
    return CompiledWorkflow(
        spec=compiled_spec,
        graph=graph,
        order=order,
        roots=roots,
        sha256=_canonical_sha(compiled_spec),
    )


def _upstream(stage: str, graph: dict[str, list[str]]) -> set[str]:
    seen: set[str] = set()
    frontier = list(graph.get(stage, []))
    while frontier:
        node = frontier.pop()
        if node not in seen:
            seen.add(node)
            frontier.extend(graph.get(node, []))
    return seen


def _sensor_problems(path: str, stage: StageSpec, graph: dict[str, list[str]]) -> list[str]:
    problems: list[str] = []
    keys = [s.key for s in stage.sensors]
    problems += [f"{path}: sensor '{k}' is listed twice" for k in sorted({k for k in keys if keys.count(k) > 1})]
    upstream = _upstream(stage.id, graph)
    for sensor in stage.sensors:
        found = config_problems(sensor.key, sensor.config)
        problems += [f"{path}.{sensor.key}: {p}" for p in found]
        if found:
            continue
        if sensor.allow_risk_acceptance and SENSORS[sensor.key].category == "security":
            problems.append(f"{path}.{sensor.key}: a security sensor cannot allow risk acceptance")
        if sensor.allow_risk_acceptance and not sensor.mandatory:
            problems.append(f"{path}.{sensor.key}: only a mandatory sensor needs risk acceptance")
        for ref in stage_references(sensor.key, sensor.config):
            if ref not in upstream:
                problems.append(f"{path}.{sensor.key}: stage '{ref}' is not upstream of '{stage.id}'")
    return problems


def _topological(graph: dict[str, list[str]]) -> tuple[list[str], list[str]]:
    """Kahn's algorithm. Returns (order, cycle); cycle is empty when the graph is a DAG."""
    indegree = {n: len(deps) for n, deps in graph.items()}
    dependents: dict[str, list[str]] = {n: [] for n in graph}
    for node, deps in graph.items():
        for d in deps:
            dependents[d].append(node)
    queue = sorted(n for n, k in indegree.items() if k == 0)
    order: list[str] = []
    while queue:
        node = queue.pop(0)
        order.append(node)
        for nxt in sorted(dependents[node]):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)
    if len(order) == len(graph):
        return order, []
    remaining = [n for n in graph if n not in order]
    return order, _find_cycle(graph, remaining[0])


def _find_cycle(graph: dict[str, list[str]], start: str) -> list[str]:
    path: list[str] = []
    node = start
    while node not in path:
        path.append(node)
        node = next(d for d in graph[node] if d in graph)
    cycle = path[path.index(node):]
    return cycle + [node]
