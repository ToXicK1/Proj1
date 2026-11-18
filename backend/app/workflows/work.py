"""Deterministic work functions for stages. No AI and no network: pure functions of the project.

A stage's definition names one of these by key. Each returns a dict that is checked against the
stage's output_required_keys. Real AI-backed work arrives with the provider layer (Milestone 5).
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class WorkContext:
    project_name: str
    project_description: str
    project_type: str
    revision: int = 1  # 1 for the first run; each rework increments it
    feedback: tuple[str, ...] = field(default_factory=tuple)  # open change requests this run answers


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


WORK_FUNCTIONS: dict[str, Callable[[WorkContext], dict[str, Any]]] = {
    "intake_summary": intake_summary,
    "requirements_outline": requirements_outline,
}
