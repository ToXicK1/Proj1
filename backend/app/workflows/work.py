"""Deterministic work functions for stages. No AI and no network: pure functions of the project.

A stage's definition names one of these by key. Each returns a dict that is checked against the
stage's output_required_keys. Real AI-backed work arrives with the provider layer (Milestone 5).
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WorkContext:
    project_name: str
    project_description: str
    project_type: str


def intake_summary(ctx: WorkContext) -> dict[str, Any]:
    words = ctx.project_description.split()
    return {
        "project_name": ctx.project_name,
        "project_type": ctx.project_type,
        "word_count": len(words),
        "has_description": bool(words),
    }


def requirements_outline(ctx: WorkContext) -> dict[str, Any]:
    return {
        "sections": ["Purpose", "Users", "Functional requirements", "Non-functional requirements"],
        "project_type": ctx.project_type,
    }


WORK_FUNCTIONS: dict[str, Callable[[WorkContext], dict[str, Any]]] = {
    "intake_summary": intake_summary,
    "requirements_outline": requirements_outline,
}
