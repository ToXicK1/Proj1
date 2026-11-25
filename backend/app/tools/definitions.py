"""Tool definitions (Phase 1c): the reviewed source of what each tool is.

Every tool an agent could ever hold is defined here, in code that goes through review: its permission class, the
departments it is authorised for, where it runs, its limits, its risk and whether a human must approve its use. The
database registry (`tool_registry`) mirrors these definitions version by version and adds what changes at run time:
whether an administrator has enabled the tool, and its health. Tools cannot be added through the API; a new tool
(including a CLI-Anything harness) arrives only through a reviewed change here, pinned to its source.

Agents still hold explicit grants on their versions, and only classes with a policy can be granted
(app/agents/tools.py).
"""

from dataclasses import asdict, dataclass, field
from typing import Any

ENGINEERING = ("business_analyst", "solution_architect", "ui_ux_designer", "software_developer", "qa_security",
               "devops_release")
CODE = ("software_developer", "qa_security", "devops_release")
_NONE: dict[str, Any] = {"type": "object", "properties": {}, "additionalProperties": False}


@dataclass(frozen=True)
class ToolDefinition:
    key: str
    version: int
    name: str
    description: str
    permission_class: str  # READ, WRITE, EXECUTE, ADMINISTRATIVE, EXTERNAL_SIDE_EFFECT
    departments: tuple[str, ...]  # who may be granted it ("*": every department, including the PM)
    actions: tuple[str, ...]
    environment: str  # in_process (reads the database) or executor (a locked-down container per call)
    adapter: str = "native"  # native, executor, git, browser, cli_anything
    executor_kind: str | None = None  # the executor job kind it maps to
    input_schema: dict[str, Any] = field(default_factory=lambda: dict(_NONE))
    output_schema: dict[str, Any] = field(default_factory=lambda: {"type": "object"})
    timeout_seconds: int = 30
    limits: dict[str, Any] = field(default_factory=dict)
    risk: str = "low"  # low, medium, high, critical
    approval: str = "none"  # none, or human: a person approves each use before it runs
    audit: str = "every_call"
    source: str = "platform"  # for third-party adapters: the pinned source (repository and commit)

    def record(self) -> dict[str, Any]:
        out = asdict(self)
        out["departments"], out["actions"] = list(self.departments), list(self.actions)
        return out


DEFINITIONS: dict[str, ToolDefinition] = {d.key: d for d in (
    ToolDefinition("read_project", 1, "Read project", "Read the project's name, type and description, and the brief "
                   "the owner confirmed.", "READ", ("*",), ("read",), "in_process"),
    ToolDefinition("list_approved_work", 1, "List approved work", "List the approved earlier deliverables the agent "
                   "may read.", "READ", ("*",), ("list",), "in_process"),
    ToolDefinition("read_artifact", 1, "Read artifact", "Read one approved earlier deliverable, or one field of it.",
                   "READ", ("*",), ("read",), "in_process",
                   input_schema={"type": "object", "properties": {"stage": {"type": "string"},
                                                                  "field": {"type": "string"}},
                                 "required": ["stage"], "additionalProperties": False}),
    ToolDefinition("search_approved_work", 1, "Search approved work", "Search the approved earlier deliverables.",
                   "READ", ("*",), ("search",), "in_process",
                   input_schema={"type": "object", "properties": {"query": {"type": "string"}},
                                 "required": ["query"], "additionalProperties": False}),
    # Repository and execution tools (Phase 1). They run through the executor; their agent runtime arrives with the
    # Developer IDE (Phase 2), and EXECUTE/WRITE stay ungrantable until then.
    ToolDefinition("repo_read", 1, "Read repository", "Read the project repository's files and tree at a branch or "
                   "commit.", "READ", ENGINEERING, ("tree", "read"), "executor", adapter="git",
                   executor_kind="git.read", timeout_seconds=60, limits={"files": 50, "bytes": 2_000_000}),
    ToolDefinition("repo_diff", 1, "Diff branches", "Compare a work branch with the default branch.", "READ",
                   ENGINEERING, ("diff",), "executor", adapter="git", executor_kind="git.diff", timeout_seconds=60),
    ToolDefinition("repo_commit", 1, "Commit to a work branch", "Commit files to a work branch (never the default "
                   "branch); the result goes to human review as a change set.", "WRITE", CODE, ("commit",),
                   "executor", adapter="git", executor_kind="git.commit", timeout_seconds=60, risk="medium"),
    ToolDefinition("run_checks", 1, "Build and test", "Build and unit-test files in an isolated container with no "
                   "network.", "EXECUTE", CODE, ("build", "test"), "executor", adapter="executor",
                   executor_kind="checks", timeout_seconds=180, risk="medium",
                   limits={"memory": "768m", "cpus": 1.0, "pids": 128, "network": "none"}),
    # Defined so they can be refused by name: no agent may ever hold these.
    ToolDefinition("merge_change_set", 1, "Merge a change set", "Merge an approved change set into the default "
                   "branch. People only.", "ADMINISTRATIVE", (), ("merge",), "executor", adapter="git",
                   executor_kind="git.merge", risk="high", approval="human"),
    ToolDefinition("write_note", 1, "Write a note", "Reserved.", "WRITE", (), ("write",), "in_process"),
    ToolDefinition("run_tests", 1, "Run tests (legacy name)", "Reserved; use run_checks.", "EXECUTE", (), ("test",),
                   "executor"),
    ToolDefinition("edit_rules", 1, "Edit rules", "Reserved: rules change only through governed proposals.",
                   "ADMINISTRATIVE", (), ("edit",), "in_process", risk="high", approval="human"),
    ToolDefinition("publish_release", 1, "Publish a release", "Reserved: production deployment is disabled until an "
                   "infrastructure provider is chosen and authorised.", "EXTERNAL_SIDE_EFFECT", (), ("publish",),
                   "executor", risk="critical", approval="human"),
)}
