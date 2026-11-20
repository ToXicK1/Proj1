# Architecture: AI-DLC Orchestration Platform

Status: Proposed (Milestone 1). Owner: Principal Architect role. Last reviewed: 2026-11-18.
Companion documents: `SYSTEM_DESIGN.md`, `DATA_FLOW.md`, `WORKFLOW_ENGINE.md`, `APPROVAL_GOVERNANCE.md`, `AGENT_ARCHITECTURE.md`, `SECURITY_ARCHITECTURE.md`, `TEST_STRATEGY.md`, `DECISIONS.md`, `USER_PORTAL.md`.

## 1. Principles

The operating rule from the master brief is binding on every component:

> AI GENERATES. AI AGENTS COLLABORATE. DETERMINISTIC SYSTEMS VALIDATE. HUMANS AUTHORIZE. THE WORKFLOW ENGINE ADVANCES.

Consequences:

1. **The workflow engine is the only writer of stage state.** Agents, users and the frontend submit *requests*; the engine decides.
2. **Approvals are human-only, server-enforced, version-bound.**
3. **Mandatory sensors and hooks fail closed.**
4. **Every external side effect has an authorization policy.**
5. **Configuration is data.** Profiles, workflows, rules, hooks and sensors are versioned records, and running executions pin their snapshot.
6. **Isolation is a property of every query**, not a UI filter.

## 2. Logical architecture

```
                 +----------------------------+
 Admin browser ->|  Web App (React/TS)        |  Two experiences, one API:
 End-user       >|  - Internal workspace      |   Internal: profiles, studio, approvals, audit
 browser        |  - User Portal (owner)     |   Portal: projects, conversations, reviews
                 +-------------+--------------+
                               | HTTPS/JSON (cookie session + CSRF)
                 +-------------v--------------+
                 |  API Gateway (FastAPI)     |  authN, rate limit, tenant context,
                 |  routers by bounded context|  request validation, error normalization
                 +-------------+--------------+
                               |
   +---------------------------+------------------------------------------+
   | Domain services (one module per bounded context, no cross-module SQL) |
   |  identity | organizations | projects | profiles | workflows (engine)  |
   |  approvals | agents | providers | hooks | sensors | rules | tools    |
   |  skills | artifacts | audit | notifications | portal (intake,        |
   |  routing, change requests) |                                         |
   +---------------------------+------------------------------------------+
        |                |                 |                 |
   PostgreSQL       Object store      Job queue (DB-backed) Secret store
   (state, audit)   (S3 API;          workers run agent     (envelope
                     MinIO in dev)    runs, sensors, hooks  encryption)
                                            |
                                  Provider adapters -> Claude / OpenAI /
                                  Gemini / OpenAI-compatible / local
```

Bounded contexts and what they own:

| Context | Owns | Must not write |
|---|---|---|
| identity | users, sessions, credentials, principals | workflow tables |
| organizations / projects | tenants, teams, project membership | approvals |
| profiles / agents / skills / tools | definitions and versions | runs |
| workflows | definitions, versions, executions, stage state machine | artifacts content |
| approvals | approval policies, approval decisions, risk acceptances | AI-generated approval rows |
| artifacts | artifact logical records, immutable versions, content in object store | stage state |
| providers | adapter configs, model routes, usage | business state |
| hooks / sensors / rules | definitions, executions, results | stage state directly (only via engine events) |
| audit | append-only chained events | any other table |
| portal | intake, conversations, messages, change requests, notifications | workflow state directly (calls engine commands) |

## 3. Technology stack (recommendation)

Chosen after inspecting the environment: Windows 11, Node 25.9, Python 3.13.14, Docker 29.5, Git 2.54. GitHub CLI is not installed.

| Layer | Choice | Why | Alternatives considered |
|---|---|---|---|
| Backend language | Python 3.13 | Team skill set in brief; strong AI SDKs; Pydantic typing | Node/TS (shared types with frontend, weaker enforcement tooling for DB constraints) |
| API framework | FastAPI | Typed request/response, OpenAPI generation, async | Django (heavier admin, less typed API), Flask (manual validation) |
| Validation | Pydantic v2 | Structured outputs and schema validation for LLM responses and API | dataclasses + manual checks |
| ORM and migrations | SQLAlchemy 2.x + Alembic | Mature, explicit transactions, locking control | SQLModel (less control), raw SQL (more effort) |
| Database | PostgreSQL 16+ | Transactions, `SELECT FOR UPDATE`, JSONB for schemas, CHECK constraints, partial indexes | MySQL (weaker constraint support for our needs) |
| Job execution | DB-backed queue (`jobs` table, `SKIP LOCKED`) with a worker process | No extra infrastructure; transactional enqueue with the state change; durable | Celery + Redis (adds broker; revisit at scale), Temporal (strong durability, large operational cost; revisit for M10) |
| Cache / rate limit | Postgres initially; Redis only when measured need | Avoids unjustified dependency | Redis from day one (rejected: not yet justified) |
| Object storage | S3 API; MinIO in Docker Compose; local-disk adapter for tests | Large artifacts, portable | Store blobs in Postgres (rejected for size) |
| AI | Own provider interface; adapters via official SDKs (Anthropic, OpenAI, Google GenAI) plus an OpenAI-compatible HTTP adapter | Provider independence; no framework lock-in | LangChain/LlamaIndex (rejected: abstraction hides the control we need for schema, cost and audit) |
| Frontend | React 18+, TypeScript, Vite, Tailwind CSS, TanStack Query | Mature, typed, fast dev loop | Next.js (SSR not needed for an authenticated app) |
| Components | Radix UI primitives + a small in-house design system | Accessible primitives (WAI-ARIA) with our styling | Full component kits (heavier theming work) |
| Workflow Studio canvas | React Flow (xyflow) | Node editor with typed nodes and edges | Custom canvas (cost too high) |
| Frontend tests | Vitest + Testing Library | Fast, same toolchain as Vite | Jest (slower with Vite) |
| E2E tests | Playwright | Cross-browser, reliable; used for portal and approval flows | Cypress (fine, but Playwright chosen for parallelism) |
| Backend tests | pytest, pytest-asyncio, testcontainers-style Postgres via Docker Compose | Standard | unittest (less ergonomic) |
| Security tooling | pip-audit, npm audit, gitleaks, Semgrep (SAST), Bandit | Covers deps, secrets, SAST | Snyk (commercial; optional later) |
| Packaging | uv for Python, pnpm for Node | Fast, lockfiles | pip/poetry (slower), npm (ok but slower) |
| Containers | Docker, Docker Compose for dev | Matches installed tooling | Podman (not installed) |
| CI | GitHub Actions (planned; repository not yet on GitHub) | Standard | GitLab CI (no repo there) |

Not introduced now (on purpose): Kubernetes, Kafka, a separate vector database, Redis, GraphQL, microservices. Each is revisited only with measured need (see `DECISIONS.md`).

## 4. Deployment shape

- **Development:** `docker compose up` starts PostgreSQL, MinIO, the API (uvicorn, reload), the worker, and the frontend dev server. Secrets come from a local `.env` that is git-ignored.
- **Production target (M10):** the same containers behind a TLS reverse proxy; one API image, one worker image (same code, different entrypoint), static frontend bundle; PostgreSQL managed service; object storage bucket with versioning; secrets from the platform secret manager.

## 5. Repository layout

As created in this milestone (`backend/app/*` maps one-to-one to the bounded contexts above; `frontend/src/*` maps to the navigation in `USER_PORTAL.md` and the internal console). There is no `shared/` folder: the API contract lives in the backend's Pydantic models and the frontend's `api.ts`. See `SYSTEM_DESIGN.md` section 2 for the current layout.

## 6. Non-negotiable invariants (checked by tests)

| ID | Invariant | Where enforced | Test |
|---|---|---|---|
| I-1 | Stage status changes only through the engine transition function | Service layer + DB trigger that rejects status UPDATE outside engine role | `tests/integration/test_engine_only_transitions.py` (to write in M3) |
| I-2 | An approval row has a human actor | CHECK constraint + service check | M4 security test |
| I-3 | An approval binds to one artifact version and its content hash | Foreign key + hash column + transactional recheck | M4 |
| I-4 | A new artifact version supersedes prior approvals of that deliverable | Engine event handler | M4 |
| I-5 | No cross-tenant read or write | Tenant scope in repository base class + negative tests | M2 security |
| I-6 | Audit rows are append-only and hash-chained | DB privileges + trigger + verification job | M2 |
| I-7 | Provider keys never leave the backend | Schema tests on every response model; log redaction | M5 |
| I-8 | Mandatory sensor failure blocks the gate | Engine precondition | M7 |
| I-9 | Users cannot invoke agents or tools directly | Portal routing returns typed actions only; no tool names in API | M9 security test |
