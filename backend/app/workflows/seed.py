"""Platform workflow templates. Seeding is idempotent: a template already stored is not stored twice."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.workflows.models import WorkflowDefinition, WorkflowVersion
from app.workflows.service import publish_version

DISCOVERY_FOUNDATION: dict[str, Any] = {
    "key": "discovery-foundation",
    "name": "Discovery foundation",
    "execution": "sequential",
    "stages": [
        {
            "id": "intake",
            "name": "Requirement intake",
            "depends_on": [],
            "work": "intake_summary",
            "output_required_keys": ["project_name", "word_count"],
        },
        {
            "id": "outline",
            "name": "Requirements outline",
            "depends_on": ["intake"],
            "protected": True,
            "approval_policy": {"type": "single", "role": "project_owner"},
            "work": "requirements_outline",
            "output_required_keys": ["sections"],
        },
    ],
}

TEMPLATES: list[dict[str, Any]] = [DISCOVERY_FOUNDATION]


def seed_templates(db: Session) -> list[WorkflowVersion]:
    """Publish each platform template that is not stored yet. Returns the versions created."""
    created: list[WorkflowVersion] = []
    for template in TEMPLATES:
        exists = db.execute(
            select(WorkflowDefinition).where(WorkflowDefinition.key == template["key"])
        ).scalar_one_or_none()
        if exists is None:
            created.append(publish_version(db, template))
    return created
