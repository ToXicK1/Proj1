# Implementation Status

Last updated: 2026-11-19 (Milestone 2)

## Summary

| Milestone | State | Evidence |
|---|---|---|
| M1 Research and architecture | Done, pushed to GitHub | `docs/research/*`, `docs/*`, commit `0ba9f98` |
| M2 Application foundation | **Implemented; partly verified** (see below) | 27 backend tests, 3 frontend tests, live HTTP smoke run |
| M3 Workflow engine | Partly done: engine, compiler and API built; approvals needed to advance past the first gate (M4) | 87 backend tests; live API check |
| M4–M10 | Not started | — |

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
| Publishing definitions over an API | Not built | Seeded from code (`app/workflows/seed.py`). Admin publishing comes with Workflow Studio (M8) |
| Job queue for workers | Not built | Stage runs happen inline; the design calls for a DB-backed queue (ADR-004) |

Public API (owner only; users never drive stages):
- `POST /api/v1/projects/{id}/workflow-executions` (CSRF; project owner only) starts an execution.
- `GET /api/v1/workflow-executions/{id}` returns stage names, statuses and versions. It never returns stage outputs or the transition log.
- No endpoint accepts a status. A body containing `status` is a validation error.

Verification:
- `backend/`: 87 tests pass (state machine: every edge against every actor; compiler: each invalid class; engine: transitions, readiness, audit chain, concurrency, failure paths, API authorization and view contents). Schema drift test passes with migration 0002.
- Live API on the Compose stack: start refused without CSRF (403), start succeeds (201), roots READY and dependents NOT_STARTED, unknown version (404), status in body (422), audit row written.
