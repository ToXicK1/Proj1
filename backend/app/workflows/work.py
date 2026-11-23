"""Deterministic work functions for stages. No AI and no network: pure functions of the project.

A stage's definition names one of these by key. Each returns a dict that is checked against the
stage's output_required_keys. Real AI-backed work arrives with the provider layer (Milestone 5).
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.providers.tasks import AI_TASKS


@dataclass(frozen=True)
class WorkContext:
    project_name: str
    project_description: str
    project_type: str
    revision: int = 1  # 1 for the first run; each rework increments it
    feedback: tuple[str, ...] = field(default_factory=tuple)  # open change requests this run answers
    intake: tuple[str, ...] = field(default_factory=tuple)  # the brief the owner confirmed
    upstream: tuple[str, ...] = field(default_factory=tuple)  # approved deliverables this stage builds on
    # For each item in upstream: its name, why it was chosen, and how much of it fitted
    upstream_info: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    # Advisory notes from support specialists, gathered just before the lead works
    contributions: tuple[str, ...] = field(default_factory=tuple)


def intake_summary(ctx: WorkContext) -> dict[str, Any]:
    words = ctx.project_description.split()
    return {
        "project_name": ctx.project_name,
        "project_type": ctx.project_type,
        "word_count": len(words),
        "has_description": bool(words),
        "revision": ctx.revision,
        "feedback_addressed": len(ctx.feedback),
    }


def requirements_outline(ctx: WorkContext) -> dict[str, Any]:
    return {
        "sections": ["Purpose", "Users", "Functional requirements", "Non-functional requirements"],
        "project_type": ctx.project_type,
        "revision": ctx.revision,
        "feedback_addressed": len(ctx.feedback),
    }


def workspace_scaffold(ctx: WorkContext) -> dict[str, Any]:
    return {"project_name": ctx.project_name, "project_type": ctx.project_type}


def workspace_detection(ctx: WorkContext) -> dict[str, Any]:
    return {"project_kind": ctx.project_type, "has_description": bool(ctx.project_description.strip())}


def state_initialization(ctx: WorkContext) -> dict[str, Any]:
    return {"brief_items": len(ctx.intake), "revision": ctx.revision}


def department_review(ctx: WorkContext) -> dict[str, Any]:
    """Human Professional Review: the department's approved work, gathered for one decision on the whole."""
    return {"package": [{"name": (ctx.upstream_info[i] or {}).get("name", f"step {i + 1}") if i < len(ctx.upstream_info)
                         else f"step {i + 1}", "content": text} for i, text in enumerate(ctx.upstream)],
            "revision": ctx.revision, "feedback_addressed": len(ctx.feedback)}


def owner_review(ctx: WorkContext) -> dict[str, Any]:
    """User Review and Approval: what the owner is shown before giving input (RD-2: the owner never approves)."""
    return department_review(ctx)


WORK_FUNCTIONS: dict[str, Callable[[WorkContext], dict[str, Any]]] = {
    "department_review": department_review,
    "owner_review": owner_review,
    "intake_summary": intake_summary,
    "requirements_outline": requirements_outline,
    "workspace_scaffold": workspace_scaffold,
    "workspace_detection": workspace_detection,
    "state_initialization": state_initialization,
}

# Every work key a stage may name: deterministic functions and AI-backed tasks.
KNOWN_WORK: frozenset[str] = frozenset(WORK_FUNCTIONS) | frozenset(AI_TASKS)
