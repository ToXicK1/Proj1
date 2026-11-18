# Implementation Status

Last updated: 2026-11-19 (Milestone 2)

## Summary

| Milestone | State | Evidence |
|---|---|---|
| M1 Research and architecture | Done, pushed to GitHub | `docs/research/*`, `docs/*`, commit `0ba9f98` |
| M2 Application foundation | **Implemented; partly verified** (see below) | 27 backend tests, 3 frontend tests, live HTTP smoke run |
| M3–M10 | Not started | — |

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
