# Database Design (target)

PostgreSQL 16, migrations with Alembic, UUIDv7 keys, every tenant-owned row carries `organization_id` (and `project_id` where it applies). Append-only tables are protected by triggers. Existing tables are kept; new ones are marked **new**.

## Identity, tenancy and permissions

| Table | Notes |
|---|---|
| organizations, users, memberships | Exist. Membership has role and status (pending, active) |
| roles, role_permissions | **new**. Named permission sets (org admin, project owner, professional, viewer) replacing hard-coded role checks |
| member_profiles | Exists. Becomes organization-level professional qualification |
| reviewer_assignments | **new**. (project or organization, profile, user, rank primary or backup, active window, assigned_by). History kept |
| projects, project_members | Exist |

## Workflow

| Table | Notes |
|---|---|
| workflow_definitions, workflow_versions | Exist. Versions immutable; projects pinned |
| stage_definitions | **new** (derived from compiled versions). id, department, sequence, inputs, outputs, gate type, retry and timeout policy |
| stage_dependencies | **new**. Edge list with condition expressions |
| workflow_executions, stage_executions, stage_transitions | Exist. New states added (UNDER_REVIEW, AWAITING_USER_INPUT, AWAITING_APPROVAL, COMPLETED) |
| jobs | **new**. Queue: kind, payload, status, attempts, run_after, locked_by, correlation_id |

## Agents and execution

| Table | Notes |
|---|---|
| profiles, agent_configurations, agent_config_versions | Exist. Agents gain department, specialty and task types |
| skills, skill_versions | Exist |
| ai_providers, model_routes, secret_references | Exist |
| routing_policies | **new**. Task type, complexity and cost rules to routes |
| agent_runs, token_usage | Exist. Become agent executions with input artifact references, context package digest, output artifact, cost, correlation ID |
| context_packages | **new**. What each execution received (references and digests, never raw secrets) |
| tool_definitions, tool_permissions, tool_executions | **new**. Registry, grants per agent version, every call recorded |

## Content

| Table | Notes |
|---|---|
| artifacts, artifact_versions | Exist. Add kind, department, storage key for large content, status (draft, under review, approved, superseded) |
| requirements, requirement_links | **new**. Requirement IDs extracted from approved BA artifacts; links to design, code and tests for traceability |
| files, file_versions, file_extractions, knowledge_chunks | **new**. Provenance, scan status, authority, classification, per-department visibility |
| change_requests | Exist. Gains origin, routing and status machine |

## Review and approval

| Table | Notes |
|---|---|
| review_records | Exist (AI reviews). Become reviews with findings |
| review_findings | **new**. Severity, evidence, status, raised by AI or human |
| review_packages | **new**. Frozen bundle: artifact version, sensor results, AI review, context summary |
| approval_decisions | Exist. Add review_package_id, profile, decision kinds (escalate, reassign) |
| escalations | **new** |

## Collaboration

| Table | Notes |
|---|---|
| channels | **new**. Type (team room, direct, handoff, review, blocker, decision), project, stage, participants |
| messages | **new** (replaces portal_messages over time). Sender type (AI profile, human, system), recipient, type, content, artifact references, visibility, thread, correlation ID |
| handoffs, decisions | **new**. Structured records linked to messages and artifacts |

## Governance and audit

sensors (registry in code), sensor_executions and sensor_evidence (exist; add input and output digests, duration), hooks and hook_executions (exist), rules and rule_versions (exist), change_proposals (exist), notifications (exist), audit_events (exist, hash-chained; add correlation ID).

## Indexes and isolation

Composite indexes on (organization_id, project_id) and on queue columns (status, run_after). Every query path filters by tenant; tests in `test_tenant_isolation.py` extend to every new table.
