# Data Flow

Status: Proposed (Milestone 1).

## 1. Stage execution with human approval

```
Owner/Admin  --POST commands/start-->  API  --authz + tenant check-->  Workflow service
                                                                          |
                             TX: lock stage row, validate READY->RUNNING,  |
                             audit "stage.started", insert job            |
                                                                          v
Worker: claim job (SKIP LOCKED) -> load pinned stage version, agent config version,
        input artifact versions (by hash) -> build context from context policy
        -> provider adapter call (timeout, retries, fallback, schema validation)
        -> store output as artifact_version (object store + row, hash)
        -> agent_run + token_usage rows
        -> TX: RUNNING->AI_COMPLETED, audit, enqueue validation job

Worker: validation job -> sensors on artifact_version (deterministic)
        -> reviewer agent run (separate config/context) -> findings stored
        -> TX: VALIDATING->AWAITING_HUMAN_REVIEW or BLOCKED, audit, notification

Human: GET stage review view (artifact version, sensors, findings, history)
       -> POST approval-decisions {artifact_version_id, decision, idempotency_key}
       -> API authz (human, role, not author, version is current gate version)
       -> TX: lock stage row, re-hash artifact version, insert approval,
              evaluate policy slots, if satisfied AWAITING->APPROVED, audit,
              invalidate dependents if needed, notify
```

Nothing in this flow lets the model write `status`. The model's only output channel is an artifact version and an agent run record, both validated.

## 2. Revision after requested changes

```
Human: POST commands/request-changes {comment, artifact_version_id}
  -> TX: AWAITING->CHANGES_REQUESTED, change_request rows created, audit
Worker: revision job -> lead agent with feedback as structured handoff
  -> new artifact_version (V+1, parent V) -> TX: CHANGES_REQUESTED->RUNNING->AI_COMPLETED
  -> validation (sensors, reviewer) -> AWAITING_HUMAN_REVIEW (V+1)
  -> change_request.resulting_artifact_version_id = V+1, status resolved by reviewer+human
Approvals for V: SUPERSEDED (kept for history)
```

## 3. Owner message routing (portal)

```
Owner message -> POST /api/v1/portal/projects/{id}/messages
  -> authz: project_owner membership, project not archived
  -> persist message (raw body, author, project, optional artifact reference)
  -> classifier (LLM or rules, behind provider abstraction) returns:
       { intent: enum, subject: enum, target_profile_key: enum,
         related_artifact_version_id?: uuid, confidence }
  -> backend validates:
       - intent in allowed enum
       - target profile belongs to the project's workflow version
       - artifact version belongs to project and is visible to owner
       - the (intent, stage state, owner permissions) combination is allowed
  -> if allowed: routed to profile via engine command (e.g., create change_request,
     record feedback on artifact, submit approval form link) — never direct tool call
  -> reply composed from templates + sanitized summary; representative voice
  -> audit: message.received, message.routed (with classifier version), action taken
```

If classification confidence is low or the intent is unsupported, the portal asks one clarifying question (no action taken).

## 4. Intake (project creation)

```
Owner creates project (type card or free text) -> projects row (status: INTAKE)
Owner conversation turns -> messages (raw), extracted fields accumulate in intake_records.structured_json
  each field tagged: explicit | inferred | uncertain | needs_clarification
Uploads -> uploaded_files (scan, hash, untrusted text extraction, never executed)
Intake complete (or owner says "you decide") -> intake package generated
  -> owner summary shown (what we understand, problem, users, features, assumptions, questions)
  -> owner confirms or corrects (corrections create new intake revisions)
  -> confirmed package routed to Business Analyst profile -> workflow execution starts
```

Assumptions never become confirmed requirements without owner confirmation or a BA-approved item.

## 5. Audit and observability

Every arrow above that changes state writes an audit event in the same transaction. Provider calls write `token_usage` and an audit `provider.call` event with redacted metadata. Correlation ID propagates from the HTTP request header (`X-Request-ID`, generated if absent) through jobs and provider calls.

## 6. Data classification

| Class | Examples | Handling |
|---|---|---|
| Secret | provider keys, session tokens, DB credentials | Encrypted at rest, never logged, never returned |
| Confidential | internal prompts, agent instructions, reasoning, raw provider payloads | Stored with restricted access; never exposed to owners |
| Customer project data | requirements, uploads, artifacts, conversations | Tenant-isolated; retention policy applies |
| Operational | timings, counts, statuses | Retained for audit and monitoring |
