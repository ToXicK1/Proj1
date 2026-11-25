"""The tools an agent can call while it works. All are READ: they look, never change anything.

Every call is checked against the grants on the agent's version, scoped to the stage being worked on, and
recorded. An agent can only see approved work from stages upstream of its own stage in the same execution: never
drafts, never later stages, never another project. Results are bounded and handed back as data, never as
instructions.
"""

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.tools import TOOL_CATALOG
from app.artifacts import service as artifacts
from app.projects.models import Project
from app.workflows.models import StageDependency, StageExecution, WorkflowExecution, WorkflowVersion

MAX_RESULT_CHARS = 3000
MAX_CALLS_PER_RUN = 8
DONE = ("APPROVED",)  # human-approved deliverables only, as in the context the engine builds

DEFINITIONS: dict[str, dict[str, Any]] = {
    "read_project": {
        "description": "Read the project's name, type and description, and the brief the owner confirmed.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "list_approved_work": {
        "description": "List the approved earlier deliverables you may read, with their stage keys, fields and sizes.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "read_artifact": {
        "description": "Read one approved earlier deliverable by its stage key. Optionally only one field of it.",
        "parameters": {"type": "object", "properties": {
            "stage": {"type": "string", "description": "Stage key, from list_approved_work"},
            "field": {"type": "string", "description": "Optional: one field of the deliverable"},
        }, "required": ["stage"], "additionalProperties": False},
    },
    "search_approved_work": {
        "description": "Search the approved earlier deliverables for words and get short matching passages.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "Words to look for"},
        }, "required": ["query"], "additionalProperties": False},
    },
}
RUNNABLE = frozenset(DEFINITIONS)


def schemas(grants: list[str]) -> list[dict[str, Any]]:
    """OpenAI-style tool definitions for the granted tools that can run."""
    return [{"type": "function", "function": {"name": name, **DEFINITIONS[name]}}
            for name in grants if name in RUNNABLE]


@dataclass
class ToolScope:
    db: Session
    stage_execution_id: uuid.UUID
    grants: tuple[str, ...]
    calls: int = 0
    log: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ToolResult:
    status: str  # ok, refused, error
    content: str  # what goes back to the model
    summary: str  # what the activity log and the record say


def _bounded(payload: Any) -> str:
    text = json.dumps({"data": payload}, ensure_ascii=False, default=str)
    if len(text) <= MAX_RESULT_CHARS:
        return text
    return text[:MAX_RESULT_CHARS - 40] + '…", "note": "cut to fit; read one field"}'


def _upstream(scope: ToolScope) -> dict[str, tuple[str, dict[str, Any]]]:
    """Approved work the agent may read: stage key -> (name, content), for stages upstream of its own."""
    db = scope.db
    stage = db.get(StageExecution, scope.stage_execution_id)
    execution = db.get(WorkflowExecution, stage.workflow_execution_id)
    needs: dict[str, list[str]] = {}
    for row in db.execute(select(StageDependency).where(StageDependency.workflow_execution_id == execution.id)):
        needs.setdefault(row[0].stage_key, []).append(row[0].depends_on)
    seen: set[str] = set()
    frontier = list(needs.get(stage.stage_key, []))
    while frontier:
        key = frontier.pop()
        if key not in seen:
            seen.add(key)
            frontier.extend(needs.get(key, []))
    names = {s["id"]: s["name"] for s in db.get(WorkflowVersion, execution.workflow_version_id).spec_json["stages"]}
    rows = db.execute(select(StageExecution).where(StageExecution.workflow_execution_id == execution.id,
                                                   StageExecution.stage_key.in_(seen))).scalars()
    out: dict[str, tuple[str, dict[str, Any]]] = {}
    for row in rows:
        current = artifacts.current_version(db, row.id) if row.status in DONE else None
        if current is not None:
            out[row.stage_key] = (names.get(row.stage_key, row.stage_key), current[1].content_json)
    return out


def execute(scope: ToolScope, name: str, raw_arguments: str) -> ToolResult:
    started = time.perf_counter()
    result = _execute(scope, name, raw_arguments)
    scope.log.append({"tool": name, "status": result.status, "summary": result.summary,
                      "ms": int((time.perf_counter() - started) * 1000), "chars": len(result.content)})
    return result


def _execute(scope: ToolScope, name: str, raw_arguments: str) -> ToolResult:
    scope.calls += 1
    if scope.calls > MAX_CALLS_PER_RUN:
        return ToolResult("refused", _bounded({"error": "Tool call limit reached; answer with what you have."}),
                          "refused: too many tool calls")
    if name not in TOOL_CATALOG or name not in RUNNABLE:
        return ToolResult("refused", _bounded({"error": f"There is no tool called {name}."}), f"refused: unknown {name}")
    if name not in scope.grants:
        return ToolResult("refused", _bounded({"error": f"You are not allowed to use {name}."}),
                          f"refused: {name} is not granted to this agent")
    from app.tools.registry import disabled

    if name in disabled(scope.db):  # an administrator switched it off; grants on older versions do not override
        return ToolResult("refused", _bounded({"error": f"{name} is not available right now."}),
                          f"refused: {name} is disabled in the tool registry")
    try:
        args = json.loads(raw_arguments or "{}")
    except ValueError:
        args = None
    if not isinstance(args, dict):
        return ToolResult("error", _bounded({"error": "Arguments must be a JSON object."}), "error: bad arguments")
    allowed = set(DEFINITIONS[name]["parameters"]["properties"])
    if set(args) - allowed:
        return ToolResult("error", _bounded({"error": f"Unknown arguments: {sorted(set(args) - allowed)}"}),
                          "error: unknown arguments")

    if name == "read_project":
        stage = scope.db.get(StageExecution, scope.stage_execution_id)
        execution = scope.db.get(WorkflowExecution, stage.workflow_execution_id)
        project = scope.db.get(Project, execution.project_id)
        return ToolResult("ok", _bounded({"name": project.name, "type": project.project_type,
                                          "description": project.description,
                                          "confirmed_brief": execution.config_snapshot.get("intake", [])}),
                          "read the project and its confirmed brief")
    work = _upstream(scope)
    if name == "list_approved_work":
        listing = [{"stage": key, "name": item[0], "fields": sorted(item[1]),
                    "chars": len(json.dumps(item[1], ensure_ascii=False))} for key, item in sorted(work.items())]
        return ToolResult("ok", _bounded(listing), f"listed {len(listing)} approved deliverable(s)")
    if name == "read_artifact":
        key = str(args.get("stage", ""))
        if key not in work:
            return ToolResult("refused", _bounded({"error": f"No approved earlier deliverable '{key}' you may read."}),
                              f"refused: '{key[:60]}' is not approved earlier work for this step")
        title, content = work[key]
        wanted = args.get("field")
        if wanted is not None:
            if wanted not in content:
                return ToolResult("error", _bounded({"error": f"'{title}' has no field '{wanted}'",
                                                     "fields": sorted(content)}), "error: unknown field")
            return ToolResult("ok", _bounded({"stage": key, "field": wanted, "value": content[wanted]}),
                              f"read {title}: {wanted}")
        return ToolResult("ok", _bounded({"stage": key, "name": title, "content": content}), f"read {title}")
    # search_approved_work
    query = str(args.get("query", "")).strip().lower()
    if not 2 <= len(query) <= 80:
        return ToolResult("error", _bounded({"error": "The query must be 2 to 80 characters."}), "error: bad query")
    words = [w for w in query.split() if len(w) > 1]
    hits = []
    for key, (title, content) in sorted(work.items()):
        for field_name, value in content.items():
            text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            low = text.lower()
            at = next((low.find(w) for w in words if w in low), -1)
            if at >= 0:
                hits.append({"stage": key, "name": title, "field": field_name,
                             "passage": text[max(0, at - 80): at + 160]})
            if len(hits) >= 6:
                break
    return ToolResult("ok", _bounded(hits), f"searched approved work for '{query[:40]}': {len(hits)} passage(s)")
