"""Runs sensors against artifact versions and decides whether a gate is clear.

The gate reads stored results, never a claim from a model. A mandatory sensor is clear only with a
PASS or WARNING for the exact artifact version, or an unexpired risk acceptance the stage allows.
"""

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.approvals.models import ApprovalDecision
from app.artifacts import service as artifacts
from app.artifacts.models import Artifact, ArtifactVersion
from app.audit.service import append_event, org_chain
from app.sensors.models import RiskAcceptance, SensorEvidence, SensorExecution
from app.sensors.registry import (
    SATISFYING,
    SENSORS,
    Outcome,
    SensorContext,
    SensorStatus,
    run_sensor,
    stage_references,
)
from app.workflows.models import StageExecution, WorkflowExecution


def _severity(spec: dict[str, Any]) -> str:
    if spec.get("severity"):
        return spec["severity"]
    if SENSORS[spec["key"]].category == "security":
        return "critical"
    return "high" if spec.get("mandatory", True) else "medium"


def _stage_row(db: Session, execution_id: uuid.UUID, key: str) -> StageExecution | None:
    return db.execute(select(StageExecution).where(StageExecution.workflow_execution_id == execution_id,
                                                   StageExecution.stage_key == key)).scalar_one_or_none()


def _is_approved(db: Session, stage: StageExecution | None) -> bool:
    if stage is None or stage.status != "APPROVED":
        return False
    current = artifacts.current_version(db, stage.id)
    if current is None:
        return False
    return db.execute(select(ApprovalDecision.id).where(
        ApprovalDecision.stage_execution_id == stage.id,
        ApprovalDecision.artifact_version_id == current[1].id,
        ApprovalDecision.approval_epoch == stage.approval_epoch,
        ApprovalDecision.decision == "APPROVE",
    )).first() is not None


def context_for(db: Session, execution: WorkflowExecution, stage: StageExecution, version: ArtifactVersion,
                references: list[str]) -> SensorContext:
    artifact = db.get(Artifact, version.artifact_id)
    upstream: dict[str, dict[str, Any] | None] = {}
    approved: set[str] = set()
    for key in references:
        row = _stage_row(db, execution.id, key)
        current = artifacts.current_version(db, row.id) if row else None
        upstream[key] = current[1].content_json if current else None
        if _is_approved(db, row):
            approved.add(key)
    evidence: dict[str, dict[str, Any]] = {}
    for row in db.execute(select(SensorEvidence).where(SensorEvidence.artifact_version_id == version.id)
                          .order_by(SensorEvidence.source == "sandbox", SensorEvidence.id)).scalars():
        # A real sandbox result sorts last, so it outranks anything recorded by hand.
        evidence[row.kind] = {"outcome": row.outcome, "findings": row.findings}
    return SensorContext(
        content=version.content_json,
        artifact_version_id=str(version.id),
        version_number=version.version_number,
        stored_sha256=version.content_sha256,
        is_current_version=artifact.current_version_id == version.id,
        upstream=upstream,
        approved_stages=frozenset(approved),
        evidence=evidence,
    )


def evaluate(db: Session, execution: WorkflowExecution, stage: StageExecution, version: ArtifactVersion,
             key: str, config: dict[str, Any]) -> Outcome:
    """Run one sensor without recording it (used by hooks)."""
    return run_sensor(key, config, context_for(db, execution, stage, version, stage_references(key, config)))


def _finding_rows(key: str, outcome: Outcome, severity: str, version_id: uuid.UUID) -> list[dict[str, Any]]:
    now = datetime.now(UTC).isoformat()
    return [
        {
            "sensor": key,
            "status": outcome.status.value,
            "severity": severity,
            "finding_id": f"{key}:{hashlib.sha256(f.description.encode()).hexdigest()[:12]}",
            "description": f.description,
            "evidence": f.evidence,
            "artifact_version": str(version_id),
            "remediation": f.remediation,
            "timestamp": now,
        }
        for f in outcome.findings
    ]


def run_stage_sensors(db: Session, execution: WorkflowExecution, stage: StageExecution, spec: dict[str, Any],
                      version: ArtifactVersion) -> list[SensorExecution]:
    rows = []
    for sensor in spec.get("sensors") or []:
        key, config = sensor["key"], sensor.get("config") or {}
        outcome = evaluate(db, execution, stage, version, key, config)
        severity = _severity(sensor)
        row = SensorExecution(
            organization_id=execution.organization_id,
            project_id=execution.project_id,
            stage_execution_id=stage.id,
            artifact_version_id=version.id,
            sensor_key=key,
            sensor_version=SENSORS[key].version,
            mandatory=sensor.get("mandatory", True),
            severity=severity,
            status=outcome.status.value,
            findings=_finding_rows(key, outcome, severity, version.id),
        )
        db.add(row)
        rows.append(row)
        append_event(
            db, chain_key=org_chain(execution.organization_id), event_type="sensor.executed", actor_type="system",
            organization_id=execution.organization_id, project_id=execution.project_id,
            payload={"sensor": key, "status": outcome.status.value, "findings": len(outcome.findings),
                     "stage": stage.stage_key, "artifact_version": str(version.id)},
        )
    db.flush()
    return rows


def _latest(db: Session, stage: StageExecution, version: ArtifactVersion) -> dict[str, SensorExecution]:
    latest: dict[str, SensorExecution] = {}
    for row in db.execute(select(SensorExecution).where(
            SensorExecution.stage_execution_id == stage.id,
            SensorExecution.artifact_version_id == version.id).order_by(SensorExecution.id)).scalars():
        latest[row.sensor_key] = row
    return latest


def active_acceptances(db: Session, stage: StageExecution, version: ArtifactVersion) -> set[str]:
    now = datetime.now(UTC)
    return set(db.execute(select(RiskAcceptance.sensor_key).where(
        RiskAcceptance.stage_execution_id == stage.id,
        RiskAcceptance.artifact_version_id == version.id,
        RiskAcceptance.expires_at > now,
    )).scalars())


def summary(db: Session, stage: StageExecution, spec: dict[str, Any], version: ArtifactVersion) -> list[dict[str, Any]]:
    latest = _latest(db, stage, version)
    accepted = active_acceptances(db, stage, version)
    out = []
    for sensor in spec.get("sensors") or []:
        key = sensor["key"]
        mandatory = sensor.get("mandatory", True)
        row = latest.get(key)
        status = row.status if row else None
        satisfied = status is not None and SensorStatus(status) in SATISFYING
        risk_accepted = sensor.get("allow_risk_acceptance", False) and key in accepted
        out.append({
            "sensor": key,
            "mandatory": mandatory,
            "status": status,
            "severity": row.severity if row else _severity(sensor),
            "risk_accepted": bool(risk_accepted),
            "blocking": mandatory and not satisfied and not risk_accepted,
            "findings": row.findings if row else [],
        })
    return out


def blocking(db: Session, stage: StageExecution, spec: dict[str, Any], version: ArtifactVersion) -> list[str]:
    return [s["sensor"] for s in summary(db, stage, spec, version) if s["blocking"]]


def blocking_feedback(db: Session, stage: StageExecution, spec: dict[str, Any]) -> tuple[str, ...]:
    """Findings from blocking sensors, phrased as rework input. They never contain secret values."""
    current = artifacts.current_version(db, stage.id)
    if current is None:
        return ()
    return tuple(
        f"{item['sensor']}: {finding['description']}"
        for item in summary(db, stage, spec, current[1]) if item["blocking"] for finding in item["findings"]
    )
