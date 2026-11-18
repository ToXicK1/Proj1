# Implementation Status

Last updated: 2026-11-19 (Milestone 2)

## Summary

| Milestone | State | Evidence |
|---|---|---|
| M1 Research and architecture | Done, pushed to GitHub | `docs/research/*`, `docs/*`, commit `0ba9f98` |
| M2 Application foundation | **Implemented; partly verified** (see below) | 27 backend tests, 3 frontend tests, live HTTP smoke run |
| M3 Workflow engine | Partly done: engine, compiler and API built; approvals needed to advance past the first gate (M4) | 87 backend tests; live API check |
| M4 Human approval engine | Backend done; conditional policies, sensors and object storage are later items | 129 backend tests; migration 0003 reversible; live approval run |
| M5 AI provider layer | Built and tested offline; live vendor calls not verified (no keys) | 185 backend tests; migration 0004 reversible; live mock run on Compose |
| M6 Agent orchestration | Built and tested; skills and sandbox not built; reviews advisory | 203 backend tests, 3 live tests on a local model; migration 0005 reversible |
| M7 Hooks, sensors and rules | Backend done; see the limits in the M7 section | 289 backend tests, 4 live tests on a local model, 14 safeguard mutations caught; migration 0008 reversible |
| Member invitations | Built and tested; email is still outbox-only | 305 backend tests, 14 browser tests, 18 safeguard mutations caught; migration 0009 reversible |
| M8 Workflow Configuration Studio | Exit criterion met; see the limits in the M8 section | 325 backend tests, 19 browser tests, 25 safeguard mutations caught; migration 0010 reversible |
| M9–M10 | Not started | — |

## M2 scope and status

| Item (MASTER_PLAN M2) | Status | Notes |
|---|---|---|
| Backend skeleton: FastAPI app factory, settings, error model | Done | `backend/app/main.py`, `core/config.py`, `core/errors.py` (problem+json) |
| PostgreSQL schema and Alembic migration | Done | `backend/migrations/versions/0001_foundation.py`; drift test compares migration to models |
| Identity: self-signup, email verification, login, sessions, CSRF | Done | ADR-015. Sessions hold only SHA-256 of the cookie token; CSRF derived with HMAC |
| Lockout, rate limiting, enumeration resistance | Done | Lockout after 5 failures for 15 min. Rate limit is per process (in memory) |
| Organizations and personal workspace | Done | Verification creates a personal org with the user as `org_admin` |
| Joining an existing org by admin invite | **Not built** | ADR-015 requires it; deferred to M2.1 |
| Projects, project members, owner role | Done (creator becomes `project_owner`) | Member management endpoints not built |
| Authorization base classes | Partly | Tenant and membership checks are in service functions, not yet a shared repository base class |
| Audit hash chain (write and verify) | Done | Append-only trigger, per-chain row lock. Verifier is a service function; no API endpoint yet |
| Email delivery | Dev outbox only | Rows in `email_outbox`; no SMTP sender |
| Frontend skeleton: signup, verify, login, projects | Done | Vite + React + TypeScript; typecheck, unit tests and build pass |
| Docker Compose | Done, verified | Docker Desktop started on 2026-11-19 (engine 29.5.2). Stack builds, migrates, and serves the API and web app; the HTTP smoke flow passes against the containers |
| Object storage (MinIO) | Not in M2 | Needed from artifacts work |
| Sandbox groundwork for prototypes (ADR-017) | Not started | Planned for M6 |
| Claude Code dev assets under `.claude/` | Not started | Directories exist only |

## Verification performed

- `backend/`: `pytest` 27 passed on Python 3.12.13 against an embedded PostgreSQL server (pgserver). Covers: audit chain integrity and tamper detection, append-only trigger, concurrent appends, signup and verification, single-use tokens, lockout, enumeration resistance, CSRF on mutations, cookie flags, tenant isolation (cross-tenant reads and writes return 404), project audit events, migration-to-model drift.
- `backend/`: `ruff check` passes.
- Live run: API started with uvicorn against a dev database and exercised over HTTP: signup, unverified login refused, verification, single-use token, login with cookie, CSRF rejection, project creation, cross-tenant 404. All matched the expected results.
- `frontend/`: `tsc --noEmit` passes; 3 unit tests pass; `vite build` succeeds.

## Not verified

- Browser end-to-end tests: 11 Playwright tests in `tests/e2e`, passing on 3 consecutive runs against the Compose stack (desktop and phone viewports).
- Python 3.13 (the decided target). The dev venv is 3.12 (see DECISIONS ADR-021).
- Accessibility and responsive layout checks.
- Real email delivery.

## Environment constraints hit in this session

Windows Application Control blocks some unsigned native binaries. Workarounds are documented in DECISIONS (ADR-021 to ADR-023). Deleting the blocked `.pyd` files in the local venv is a local workaround only, not a project change.

## Milestone 3: workflow engine (2026-11-19)

Status: **Partly done.** The state machine, the compiler, the locked engine, the deterministic runner, the audit trail and the API are built and tested. Two M3 exit items are not met yet (see below).

| Item (MASTER_PLAN M3) | Status | Notes |
|---|---|---|
| Workflow definitions, versions | Done | Compiled, immutable, SHA-256 per version; only published versions run |
| Profiles and stages as data | Partly | Stages are data; profiles as first-class objects are not built |
| Dependencies (sequential only) | Done | Parallel and conditional are rejected by the compiler with a clear reason |
| State machine with all edges from WORKFLOW_ENGINE.md | Done | Actor rules: AI agents and providers appear in no allow-list |
| Workflow execution pinning its version | Done | Executions reference the version row |
| Configuration validation (compiler) | Done | Duplicate ids, unknown refs, self-dependency, cycles (path reported), unknown work, protected without policy, unsupported condition/execution, unknown fields. All problems returned at once |
| Locked, transactional transitions | Done | Execution row then stage row locked; optional expected_version; log row, audit event and readiness update in one transaction. Concurrency test: exactly one winner of six parallel attempts |
| Deterministic execution without AI | Partly | A stage runs its deterministic work, validates required output, and ends in AWAITING_HUMAN_REVIEW. **Downstream stages cannot start until approvals exist (Milestone 4)** |
| Approval, rework, invalidation | Not started | Milestone 4. Human-only edges exist in the state machine; the engine refuses APPROVED until then |
| Workflow-level status (COMPLETED, PAUSED) | Not built | Executions only ever show RUNNING |
| Publishing definitions over an API | Done in M8 | Organization admins publish from the Studio; platform templates are still seeded from code |
| Job queue for workers | Not built | Stage runs happen inline; the design calls for a DB-backed queue (ADR-004) |

Public API (owner only; users never drive stages):
- `POST /api/v1/projects/{id}/workflow-executions` (CSRF; project owner only) starts an execution.
- `GET /api/v1/workflow-executions/{id}` returns stage names, statuses and versions. It never returns stage outputs or the transition log.
- No endpoint accepts a status. A body containing `status` is a validation error.

Verification:
- `backend/`: 87 tests pass (state machine: every edge against every actor; compiler: each invalid class; engine: transitions, readiness, audit chain, concurrency, failure paths, API authorization and view contents). Schema drift test passes with migration 0002.
- Live API on the Compose stack: start refused without CSRF (403), start succeeds (201), roots READY and dependents NOT_STARTED, unknown version (404), status in body (422), audit row written.

## Milestone 4: human approval engine (2026-11-19)

Status: **Backend complete against the M4 exit criteria; gaps listed below.**

| Item (MASTER_PLAN M4) | Status | Notes |
|---|---|---|
| Versioned artifacts | Done | Immutable `artifact_versions` (trigger blocks UPDATE/DELETE); content hash; every stage output is version N |
| Approval requests and decisions | Done | Approve, reject, request changes; append-only `approval_decisions` |
| Approval policies | Done | single, any_of, all_of, role_based, sequential. Conditional is refused by the compiler (not yet supported) |
| Authorization | Done | Non-members: 404. Members without a policy role: 403. Human actors only (DB CHECK + state machine) |
| Version binding | Done | A decision names one version; a newer version makes older approvals stop counting (`stale_version`) |
| Separation of duties | Done | An author cannot approve their own version; one person fills at most one slot per version |
| Idempotency and replay | Done (partial) | Same key returns the same result; a different decision on the same key is refused. Nonce expiry not built |
| Comments and change requests | Done | Reject and request-changes need a comment. Each request is a `change_requests` row, resolved by the revision that answers it |
| Rework loop, bounded | Done | Feedback goes to the next revision (`feedback_addressed`); limit 3 loops (`rework_limit_reached`) |
| Invalidation on upstream change | Done | New upstream version: that stage and approved downstream stages go to AWAITING; approvals of the previous epoch stop counting even when the version is unchanged |
| Atomic approval | Done | Approval row, slot evaluation, stage transition, downstream readiness and workflow completion commit together. Injected failure rolls everything back (tested) |
| Concurrency | Done | Concurrent approvals from two slots: exactly one APPROVED transition (tested) |
| Workflow completion | Done | Execution moves to COMPLETED when all stages are APPROVED or SKIPPED; reopened if an upstream change lands |
| Validation snapshot | Partial | Stores version and satisfied slots. Mandatory sensors arrive with M7 and are recorded as an empty list |

API (owner or any member; CSRF on writes):
- `GET /api/v1/workflow-executions/{id}/stages/{key}/review` returns the stage, the current artifact (content included), policy slots, decisions for the current epoch, change requests, and `can_decide` for the caller.
- `POST /api/v1/workflow-executions/{id}/stages/{key}/decisions` takes `artifact_version_id`, `decision`, `comment`, `idempotency_key`. Unknown fields are refused, so a client cannot send a status or an approver.

Verification:
- `backend/`: 129 tests pass. New: 21 policy tests, approval engine tests (single, version binding, rework bound, reject, authorization, separation of duties, idempotency, append-only, all_of, sequential, concurrency, atomicity, invalidation), 5 HTTP tests, compiler policy cases.
- Migration 0003 downgrades and re-applies cleanly on the Compose database.
- Live run on the Compose stack: intake run inside the container, approval over HTTP (403 without CSRF, 200 on approve, idempotent repeat), second approval refused, outline run, request changes, rework to version 2, version-1 approval refused as stale, approval of version 2, workflow COMPLETED.

## Milestone 5: AI provider layer (2026-11-19)

Status: **Built and tested offline. Live vendor calls are NOT verified: no provider keys are configured (ADR-016).**

| Item (MASTER_PLAN M5) | Status | Notes |
|---|---|---|
| Adapters: Anthropic, OpenAI, Gemini, OpenAI-compatible, local | Built; tested against mocked HTTP | Request shape, auth headers, response parsing and error mapping are tested. Not yet proven against the live vendors |
| Mock provider for CI | Done | Deterministic, offline. Refused outside development and test |
| Common interface, normalized errors | Done | auth, rate_limited, timeout, unavailable, invalid_request, content_filtered, bad_response |
| Retries and timeouts | Done | Retryable errors back off (2 retries); auth and invalid errors are not retried. Timeout per request |
| Structured output | Done | JSON object with the task's required keys; one repair attempt on the same provider, then the next candidate |
| Fallback that keeps the schema | Done | Same request and the same key check on each candidate; each attempt is recorded |
| Model routes (primary, fallback order) | Done | Admin-defined, organization-scoped, up to 3 fallbacks |
| Token and cost tracking | Done (tokens); cost only when priced | Cost is computed only for models with an entered price. None is invented |
| Secrets: envelope encryption | Done | AES-256-GCM, random nonce per secret, associated data bound to organization and name. Plaintext never stored or returned |
| Provider health checks | Done | Admin probe per provider and model; result stored on the provider |
| Admin API: configure and test providers | Done | Organization admins only. Writes need CSRF. Keys are write-only |
| Provider calls inside the stage transaction | Done | Run records, usage and audit commit with the stage transition |
| Prompt-injection stance for owner text | Done (prompt-level) | Owner text sits in tags and the system prompt says never to follow it. Tested with an injection payload |
| No key in API responses or stored records | Tested | Canary test across read endpoints, audit payloads, run records and ciphertext. Application logs are not scanned yet |
| Live provider tests | **Not run** | Need keys and a budget. Nothing in CI calls a vendor |

Public API (organization admin; CSRF on writes):
- `POST /api/v1/orgs/{id}/providers`: name, adapter_type, base_url, api_key (write-only). Returns `key_last4` only.
- `GET /api/v1/orgs/{id}/providers`, `POST .../providers/{id}/key` (rotate), `POST .../providers/{id}/health` (probe).
- `POST /api/v1/orgs/{id}/model-routes`, `GET /api/v1/orgs/{id}/model-routes`.

Stage integration: a stage may name an AI task (`work: "ai:requirements_draft"`) and a `model_route`. The compiler requires the route for AI tasks and refuses it for deterministic ones. Output goes through the same validation and artifact versioning as M3–M4.

Verification:
- `backend/`: 185 tests pass. New: 30 adapter tests (headers, bodies, parsing, every error mapping, refusals, mock modes), 8 secret tests (round trip, nonce, binding, tamper, key length, production refusal), 18 provider product tests (admin API, RBAC, leak scan, stage on mock and on two providers, retries, fallback, repair, failure reasons, injection, cost, health).
- Migration 0004 reverses and re-applies on the Compose database.
- Live run on Compose: mock provider and route created, a stored anthropic key (never called), AI stage run inside the container through the mock, usage recorded with no cost, canary leak scan clean.

### M5 live verification update (2026-11-19)

- Live: an `openai_compatible` provider pointed at a local Ollama server (`qwen3-vl:4b-instruct`) produced a structured stage output through the full product path, with the health probe passing. Run with `pytest -m live` after setting `AIDLC_LIVE_OLLAMA_URL` and `AIDLC_LIVE_OLLAMA_MODEL`.
- Still not verified live: Anthropic, OpenAI and Gemini (no keys).

## Milestone 6: agent orchestration (2026-11-19)

Status: **Built and tested. The M6 exit criterion (independent professional profiles) is met in tests and on a local model. Skills and the development sandbox are not built.**

| Item (MASTER_PLAN M6) | Status | Notes |
|---|---|---|
| Agent registry, versioned | Done | Agents are named; each version is immutable (trigger). Runs record the version they used |
| Profiles (professional areas) | Done | Agents belong to one profile; a run refuses an agent from another profile |
| Lead and reviewer roles | Done | A stage may name one lead and one reviewer |
| Reviewer independence | Done | Compile time: same key refused. Run time: a reviewer that shares the lead's lineage (a clone) is refused |
| Context scope per agent | Done | Lead: project input and feedback, as its version allows. Reviewer: the artifact under review only. Each run stores a manifest (ids and counts, never content) |
| Structured handoff | Done | The review record carries a handoff: from run, to agent, artifact version, open questions |
| Reviewer verdict visible to the owner | Done | Shown in the review view with its findings. Advisory: it does not block the gate |
| Tool registry and grants | Done (catalogue only) | Five permission classes. Only READ can be granted; EXTERNAL and ADMINISTRATIVE are refused. No tool executes yet |
| Skills | Done (see the update below) | Versioned, pinned by agent versions |
| Development sandbox (ADR-017) | **Not built** | Needed before the design stage generates runnable code |
| Blocking reviews | **Not built** | Reviews are advisory until sensors (M7) |
| Admin API | Done | Profiles, agents, new versions, list. Org admins only |

Verification:
- `backend/`: 203 tests pass; 3 live tests pass against the local Ollama model. New: 18 agent tests (admin rules, validation refusals, immutability, compile and run-time independence, context scope, handoff, profile mismatch, review visibility, two profiles executing independently).
- Migration 0005 reverses and re-applies on the Compose database.
- Live: a lead and a reviewer on the local model (`qwen3-vl:4b-instruct`) completed a stage through the full path.

### M6 follow-up: skills and reviewer pinning (2026-11-19)

| Item | Status | Notes |
|---|---|---|
| Skill registry | Done | Organization-scoped skills with immutable versions (trigger). Org admins only |
| Pinning skills to agent versions | Done | An agent version pins the latest skill version at creation. Later skill edits do not change it; a new agent version is needed to pick them up |
| Skill checks | Done | Compatible profiles are checked, and the agent must already hold every tool the skill requires. A skill never grants a tool |
| Skills in runs | Done | Pinned instructions are added to the system prompt; the run manifest records key and version |
| Provider pinning | Done | `allow_fallback: false` on an agent version limits it to the route's primary provider. Retries on that provider still apply. The default is `true`, so reviewers are pinned only when configured |
| Compatible stages, skill dependencies | Done (see the next update) | Added after this table was written |

Verification: 215 backend tests pass (12 new in `test_skills.py`), 3 live Ollama tests pass, and migration 0006 reverses and re-applies on the Compose database. The live tests do not use a skill, so skill prompts are verified only against the scripted model.

Corrections to earlier notes in this file: test counts for M4 and M5 were recounted from pytest, and the M5 credential check no longer claims to cover application logs.

### M6 follow-up: skill stages and dependencies (2026-11-19)

- A skill version can list compatible stages. The limit is enforced when the stage runs, because workflow versions are global and agents belong to an organization; a violation fails the stage before any provider call.
- A skill version can depend on other skills. Each dependency is pinned to the exact version that existed when the skill version was created, so a later edit cannot change it and cycles cannot form through edits.
- An agent version pins the full closure, dependencies first. Profile and tool checks apply to every skill in the closure. Two versions of one skill in a closure are refused.
- A stage now refuses a lead that was not created as a lead and a reviewer that was not created as a reviewer. Before this, a lead agent could be named as a reviewer.
- Verified by 223 backend tests (8 new) and migration 0007 reversing and re-applying on the Compose database.

## Milestone 7: hooks, sensors and rules (2026-11-19)

Status: **Backend exit criteria met. There is no user interface for any of this yet.**

| Exit criterion | Result |
|---|---|
| Mandatory validations block gates | Done. A failed mandatory sensor moves the stage to BLOCKED, and approval re-checks the stored results for that exact artifact version |
| Hooks run at configured events | Done. Declarative actions only: `require_approval`, `run_sensor`, `notify` |
| Rule inheritance | Done. Organization, Team, Project, Profile, Stage, Agent; additive; binding rules cannot be redefined lower down |
| AI cannot activate a rule or hook | Done. AI output can only create a pending proposal; an organization admin must approve it |

What was built:

- **Sensors:** all 17 from the brief, with statuses PASS, FAIL, WARNING, NOT_APPLICABLE and ERROR. Results are append-only. For a mandatory sensor, only PASS or WARNING counts; ERROR and NOT_APPLICABLE do not.
- **Evidence:** lint, type check, unit tests, integration tests, security scan and dependency audit read results recorded outside the artifact. A claim written inside an artifact is ignored. A project owner cannot record evidence, and only an internal reviewer can record security evidence.
- **Risk acceptance:** only where the stage allows it, by an organization admin, with a reason and an expiry of at most 30 days, bound to one artifact version. Security sensors can never be accepted.
- **Re-validation and rework:** `POST .../validate` re-runs checks; a BLOCKED stage can be reworked with the sensor findings as feedback, within the same loop limit.
- **Hooks:** versioned, prioritized, conditional, with retries, timeouts and an append-only execution log. `fail_closed` is accepted only where the engine can really stop the operation. A refused approval keeps its log after the rollback.
- **Rules:** versioned with change history; deterministic conflict checks; resolved rule versions are added to agent prompts and recorded in the run manifest.
- **Learning loop:** a human correction can produce a proposed rule. It is checked for conflicts and takes effect only for workflows started after a person approves it.
- **Execution snapshot:** a workflow now keeps the agent versions, rule versions and teams it started with. Later edits do not change it. This closes a gap in M6, where runs used the latest agent version.
- **Notifications:** per-person records with read state.

Verification:

- `backend/`: 289 tests pass, 4 live tests skipped by default. New: sensor logic for all 17 sensors, 36 governance tests end to end.
- 14 deliberate breakages of safeguards (approval and gate ignoring sensors, evidence role check, expired acceptances, hook enforcement, disabled hooks, rule snapshot, binding rules, proposal conflicts, self-approval, skill stage limits, reviewer role, agent snapshot) were each caught by a test, and the code was restored.
- 4 live tests pass on the local `qwen3-vl:4b-instruct` model, including a stage with a pinned skill, an organization rule and three sensors.
- Migration 0008 reverses and re-applies on the Compose database.

## Member invitations (2026-11-18)

Status: **Built and tested. Invitation email is not delivered yet; the link sits in `email_outbox`.**

- Admins invite by email from the new Team page, optionally with a project role, and can revoke pending invitations, change roles and remove members.
- The `/accept-invite` page shows the invitation and accepts it for the matching signed-in account.
- Rules are enforced in the backend (ADR-048, ADR-049).
- `backend/`: 305 tests pass, 4 live tests skipped by default; 16 are in `tests/test_members.py`.
- Browser: 14 Playwright tests pass on Compose from a freshly started web container, including 3 for invitations. They now run with 2 workers (INV-4).
- 18 deliberate breakages of membership safeguards are caught. The first pass missed 5, so 3 tests were added. The invite admin check exists in both router and service, so that breakage removes both.
- Migration 0009 reverses and re-applies on the Compose database.
- Also fixed: the Create project button could be used before the organization list had loaded, which showed a false "workspace is not ready" error.
- Limits: INV-1 to INV-4 and M7-8 in `KNOWN_ISSUES.md`. An invited reviewer has no evidence screen yet (M7-9).

## Milestone 8: Workflow Configuration Studio (2026-11-18)

Status: **Exit criterion met: an administrator builds and publishes a custom profile with a custom stage and gate without code changes, and invalid configurations cannot publish.**

| Plan item | Status | Notes |
|---|---|---|
| Profile editor | Done | Profiles, agents and new agent versions |
| Stage editor | Done | Work, profile, agents, outputs, dependencies, approval gate, sensors |
| Visual workflow builder | Done | React Flow: drag to link, click a line to unlink |
| Permission editor | Partial | Agent tool grants only (M8-4) |
| Rules editor | Done | Add, update, retire, and decide proposals |
| Hooks and sensors editor | Done | Hooks are created and switched on or off; sensors are added per stage |
| Import and export | Done | JSON and YAML; imports become drafts |

- Publishing is admin only, audited, and creates an immutable version. Starting a workflow now checks that it belongs to the project's organization or is a platform template.
- `backend/`: 325 tests pass, 4 live tests skipped by default; 20 are in `tests/test_studio.py`.
- `frontend/`: 8 unit tests, typecheck and production build pass.
- Browser: 19 Playwright tests pass on Compose, including 4 Studio flows and a phone-width check.
- 25 deliberate breakages of Studio safeguards are caught.
- Migration 0010 reverses and re-applies on a clean database. Downgrade refuses while organization workflows exist, because they would otherwise become platform templates.
- Not done: M8-1 to M8-8 in `KNOWN_ISSUES.md`. A published workflow's run is proven through the API and engine tests, not through a browser screen.
