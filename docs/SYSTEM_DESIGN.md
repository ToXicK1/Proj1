# System Design

Status: Proposed (Milestone 1). Schema is a design target; migrations are written in Milestone 2 and 3.

## 1. Data model

Conventions: UUIDv7 primary keys; `created_at`, `updated_at` (UTC); `version` integer on mutable workflow rows; `organization_id` on every tenant-scoped table; soft delete only where stated (archival), never for approvals, audit or artifact versions.

### 1.1 Identity and tenancy

| Table | Key columns | Notes |
|---|---|---|
| `organizations` | id, name, status, retention_policy_id | Tenant root |
| `users` | id, email (unique, citext), password_hash, status, mfa_enabled | Human principals |
| `principals` | id, principal_type (`human`, `ai_agent`, `system`, `provider`), user_id nullable, agent_config_id nullable | CHECK: human principals have user_id; only human principals may hold approval grants |
| `memberships` | organization_id, user_id, role | Org-wide role |
| `teams` | id, organization_id, name | |
| `team_members` | team_id, user_id | |
| `roles`, `role_permissions` | role, permission | Permission strings |
| `sessions` | id, user_id, token_hash, expires_at, rotated_at, ip, user_agent_hash | Server-side sessions |

### 1.2 Projects

| Table | Key columns | Notes |
|---|---|---|
| `projects` | id, organization_id, name, description, project_type (enum + custom text), status, owner_user_id, workflow_version_id | |
| `project_members` | project_id, principal_id, project_role | `project_owner`, `internal_reviewer`, `team_member`, `viewer` |
| `project_settings` | project_id, key, value_json | Provider choice, budgets, retention |

### 1.3 Profiles, agents, skills, tools

| Table | Key columns | Notes |
|---|---|---|
| `profiles` | id, organization_id nullable (NULL = platform template), key, display_name, status | Template or org-specific |
| `profile_versions` | id, profile_id, version, definition_json, definition_sha256, created_by, created_at | Immutable |
| `professional_representatives` | id, profile_id, display_name, role_title, voice_config | User-facing identity |
| `stages` | id, profile_version_id, stage_key, name, objective, sequence, config_json | Stage definition inside a profile version |
| `stage_versions` | id, stage_id, version, definition_json, sha256 | Immutable |
| `agent_configurations` | id, organization_id, key, kind (`lead`, `support`, `reviewer`), status | |
| `agent_config_versions` | id, agent_configuration_id, version, instructions_ref, model_route_json, input_schema, output_schema, context_policy_json, retry_policy_json, timeout_seconds, sha256 | Immutable |
| `skills` / `skill_versions` | key, version, instructions, required_tools, compatible profiles/stages | |
| `tools` / `tool_versions` | key, version, input_schema, output_schema, permission_class, environment, timeout, retry, status (`pending_review`, `authorized`, `revoked`) | |
| `agent_tool_grants` | agent_config_version_id, tool_version_id, constraints_json, granted_by | Explicit grant |

### 1.4 Workflows and execution

| Table | Key columns | Notes |
|---|---|---|
| `workflow_definitions` | id, organization_id nullable, key, name | |
| `workflow_versions` | id, workflow_definition_id, version, definition_json, compiled_graph_json, sha256, compile_status, published_at | Only compiled, published versions are executable |
| `workflow_executions` | id, project_id, workflow_version_id, status, version, started_at, completed_at | Pins the version; never changes |
| `phase_executions` | id, workflow_execution_id, phase_key, status | Derived status |
| `stage_executions` | id, workflow_execution_id, phase_execution_id, stage_version_id, status, version, rework_count, lock fields | State machine owner |
| `stage_transitions` | id, stage_execution_id, from_status, to_status, actor_principal_id, reason, audit_event_id, created_at | Ordered transition log (immutable) |
| `stage_dependencies` | stage_execution_id, depends_on_stage_execution_id | Materialized from compiled graph |

### 1.5 Artifacts

| Table | Key columns | Notes |
|---|---|---|
| `artifacts` | id, project_id, stage_execution_id, kind (`brd`, `srs`, `architecture`, `design_prototype`, `source`, `test_report`, ...), title, current_version_id | Logical deliverable |
| `artifact_versions` | id, artifact_id, version_number, storage_key, content_sha256, size_bytes, mime_type, created_by_principal_id, source (`ai_run`, `human_edit`, `upload`), agent_run_id nullable, parent_version_id, created_at | **Immutable**; new content = new row |
| `artifact_comments` | id, artifact_version_id, author_principal_id, body, kind (`comment`, `change_request`, `question`), created_at | |
| `change_requests` | id, project_id, originating_message_id, artifact_version_id nullable, target_profile_id, priority, status, resolution_notes, resulting_artifact_version_id | See portal |

### 1.6 Approvals and governance

| Table | Key columns | Notes |
|---|---|---|
| `approval_policies` | id, workflow_version_id or stage_version_id, policy_json | Compiled slots |
| `approval_decisions` | id, organization_id, project_id, stage_execution_id, artifact_version_id, content_sha256, approver_principal_id, decision, comment, policy_slot, validation_snapshot_json, status (`ACTIVE`, `SUPERSEDED`, `REVOKED`), idempotency_key, decided_at | CHECK: approver is human; UNIQUE (stage_execution_id, artifact_version_id, policy_slot, approver_principal_id) |
| `risk_acceptances` | id, stage_execution_id, artifact_version_id, sensor_key, reason, approver_principal_id, expires_at, status | |
| `finding_dispositions` | id, approval_decision_id, review_finding_id, disposition | |

### 1.7 Rules, hooks, sensors, providers, usage

| Table | Key columns | Notes |
|---|---|---|
| `rules` / `rule_versions` | id, scope_type (`organization`, `team`, `project`, `profile`, `stage`, `agent`), scope_id, key, content, version, author_principal_id, status, sha256 | Additive by default; supersede chain |
| `rule_proposals` | id, source_message_id nullable, target_scope, proposed_content, conflict_report_json, status, decided_by | Requires human approval to activate |
| `hook_definitions` / `hook_versions` | event, priority, condition_json, action, permissions, timeout_ms, retry_json, failure_policy (`fail_closed`, `fail_open`, `advisory`), enabled, sha256 | Declarative |
| `hook_executions` | id, hook_version_id, event_id, status, duration_ms, result_json, error | |
| `sensor_definitions` / `sensor_versions` | key, version, implementation_key, input_schema, output_schema, default_severity, mandatory | |
| `sensor_executions` | id, sensor_version_id, artifact_version_id, status (`PASS`, `FAIL`, `WARNING`, `NOT_APPLICABLE`, `ERROR`), severity, findings_json, evidence_json, created_at | |
| `review_findings` | id, sensor_execution_id nullable, agent_run_id nullable, artifact_version_id, finding_key, severity, description, evidence_ref, remediation, status | |
| `ai_providers` | id, organization_id, adapter_type, base_url, status, health_json | No secret columns |
| `provider_credentials` | id, provider_id, secret_reference_id | Reference only |
| `model_routes` | id, organization_id, scope_type, scope_id, primary_model, fallback_models_json, policy_json | |
| `secret_references` | id, organization_id, name, ciphertext, key_version, last4, created_by, rotated_at | Ciphertext only |
| `agent_runs` | id, stage_execution_id, agent_config_version_id, kind, status, provider_id, model, started_at, ended_at, attempt, fallback_of_run_id, context_manifest_json, output_artifact_version_id nullable | |
| `token_usage` | id, agent_run_id, provider, model, input_tokens, output_tokens, cost_micro_usd, latency_ms | Price version recorded |

### 1.8 Conversations, portal and notifications

| Table | Key columns | Notes |
|---|---|---|
| `conversations` | id, project_id, scope (`project`, `profile`, `stage`), profile_id nullable, stage_execution_id nullable | Project-wide or scoped |
| `messages` | id, conversation_id, project_id, author_type (`owner`, `representative`, `system`), author_principal_id nullable, body, intent, classification_json, routed_to_profile_id, related_artifact_version_id nullable, created_at | Internal agent messages are stored in `agent_runs`, not here, and are never returned to owners |
| `intake_records` | id, project_id, raw_input_json, uploaded_file_ids, structured_json, assumptions_json, uncertainties_json, questions_json, confirmed_at, confirmed_by | Preserves explicit / inferred / uncertain / needs-clarification / BA-recommended distinction |
| `uploaded_files` | id, project_id, uploaded_by, storage_key, sha256, mime_type, size, scan_status, extracted_text_ref | Untrusted content |
| `notifications` | id, user_id, project_id, type, payload_json, status, created_at, read_at | |
| `pending_actions` | id, project_id, owner_user_id, action_type, target_ref, reason, due_at, status | Derived from workflow state; recalculated, not hand-edited |

### 1.9 Audit

| Table | Key columns | Notes |
|---|---|---|
| `audit_events` | id (bigint sequence), organization_id, project_id nullable, workflow_execution_id nullable, stage_execution_id nullable, event_type, actor_type, actor_id nullable, correlation_id, payload_json (redacted), occurred_at, prev_hash, hash | Append-only; hash over canonical JSON + prev_hash |
| `audit_checkpoints` | id, organization_id, up_to_event_id, head_hash, signature, created_at | Periodic |

Indexes (initial): `(organization_id, project_id, occurred_at)`, `(stage_execution_id)`, `(correlation_id)`, `(artifact_version_id)` on approvals, partial unique index for `ACTIVE` approvals per slot.

## 2. Repository layout (current, 2026-11-20)

```
backend/app/{core,auth,organizations,projects,agents,workflows,approvals,providers,hooks,sensors,rules,
             skills,artifacts,audit,notifications,portal,collab,studio,governance,jobs,storage,activity,tools}
backend/app/worker.py   backend/migrations   backend/tests
frontend/src/{components,pages,portal,studio}
sandbox/   infrastructure/{docker,deployment}
tests/{e2e,security}
docs/{research,architecture,development,operations,rebuild,reference-research}  + top-level architecture docs
.claude/{agents,skills,hooks}   (development-time Claude Code assets, none yet)
```

Placeholder folders from the first layout that were never used were removed on 2026-11-20: `backend/app/{api,stages,profiles}`
(routes live in each module's `router.py`, the stage engine in `workflows`, profiles in `agents`),
`frontend/src/{approvals,profiles,services,workflow-studio,workspaces}` (built as `portal` and `studio`), `shared/` and
`tests/integration` (the backend suite covers integration). `backend/app/tools` and `infrastructure/deployment` stay as
placeholders for tool calling (Phase 6) and a real deployment target.

Rule: a module may call another module's *service* interface; it may not import another module's repository or write its tables.

## 3. API design

- REST/JSON under `/api/v1`. Resources are plural nouns; state changes are explicit command sub-resources:
  - `POST /api/v1/stage-executions/{id}/commands/start`
  - `POST /api/v1/stage-executions/{id}/approval-decisions` (body includes `artifact_version_id`, `decision`, `idempotency_key`)
  - `POST /api/v1/stage-executions/{id}/commands/request-changes`
- No endpoint accepts a target `status` field. Attempting to set status is a validation error, which is the API-level form of invariant I-1.
- Errors: RFC 9457 problem details; typed codes (`invalid_transition`, `version_conflict`, `approval_not_permitted`, `sensor_blocking`, `tenant_mismatch` mapped to 404).
- Responses never include secrets, provider names unless the caller is an admin, or internal agent prompts.
- Pagination: cursor-based on audit and messages.
- OpenAPI is served by the API at `/api/docs`. Not yet done: committing it and generating the frontend client from it; today `frontend/src/api.ts` is written by hand.

Portal API is a separate prefix `/api/v1/portal/...` with its own response models (see `USER_PORTAL.md`).

## 4. Frontend structure

Two shells, one design system:

- **Internal console:** Dashboard, Projects, Profiles, Workflow Studio, Agents, Skills, Tools and Integrations, Rules and Knowledge, Hooks and Sensors, Approvals, Audit Logs, Settings. Three-panel profile workspace as in the brief.
- **Project Owner portal:** Home, My Projects, Create Project, Project Workspace (overview, team, lifecycle, conversations, requirements, architecture, design, development, testing, release, documents, activity & decisions), Deliverables, Reviews & Approvals, Notifications, Account Settings. Navigation items are shown only when the project's stage state and the user's permissions make them relevant; hidden items are still enforced by the API.

State management: server state through TanStack Query; no client-side authority for workflow state; optimistic UI disabled for approvals.

## 5. Real-time updates

Server-sent events (SSE) for project activity and stage state changes, with a `last_event_id` resume. Chosen over WebSockets because the traffic is server-to-client and SSE works through standard proxies. Events are derived from audit rows, so the UI cannot show a status the backend did not record.

## 6. Configuration lifecycle

1. Admin edits a draft (profile, workflow, rule, hook, sensor, agent).
2. Compile/validate; errors shown with paths.
3. Publish creates an immutable version with sha256.
4. New projects select a published version. Existing executions keep their pinned version.
5. Diff view between versions; rollback is "publish previous content as new version", never mutation.
