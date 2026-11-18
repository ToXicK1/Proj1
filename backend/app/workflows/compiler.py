"""Workflow definition compiler (WORKFLOW_ENGINE.md section 4).

A definition is compiled before it can be stored or executed. Invalid definitions never run.
Compilation returns every problem found, not just the first, with a path to the offending field.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.approvals.policy import PolicyError, parse_policy

ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
SUPPORTED_EXECUTION = {"sequential"}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StageSpec(_Strict):
    id: str
    name: str = Field(min_length=1, max_length=120)
    depends_on: list[str] = Field(default_factory=list)
    protected: bool = False
    approval_policy: dict[str, Any] | None = None
    work: str = Field(min_length=1, max_length=64)
    output_required_keys: list[str] = Field(default_factory=list)
    condition: str | None = None  # conditional execution is not supported in this milestone
    model_route: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_\-]{1,63}$")


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
        problems.append(f"execution: '{spec.execution}' is not supported (supported: sequential)")

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
        if is_ai and not stage.model_route:
            problems.append(f"{path}.model_route: AI task '{stage.work}' needs a model route")
        if stage.model_route and not is_ai:
            problems.append(f"{path}.model_route: only AI tasks use a model route")
        if stage.condition is not None:
            problems.append(f"{path}.condition: conditional execution is not supported yet")

    graph = {s.id: [d for d in s.depends_on if d in ids] for s in spec.stages}
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
