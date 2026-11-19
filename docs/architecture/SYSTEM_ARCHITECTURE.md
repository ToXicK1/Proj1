# System Architecture (target)

Status: proposed for the rebuild, pending decisions D1 to D8 in `docs/rebuild/REBUILD_PLAN.md`. Supersedes `docs/ARCHITECTURE.md` where they differ.

## 1. Shape

A modular monolith with one extra worker process and two isolated services.

```
Browser (React, TypeScript, Vite)
   │  same-origin /api, session cookie + CSRF
   ▼
API (FastAPI)  ── reads/writes ──►  PostgreSQL  ◄── claims jobs ──  Worker (same code, worker entrypoint)
   │                                    ▲                                 │
   │ signed URLs                        │                                 ├─► AI providers (Claude, OpenAI, Gemini, OpenAI-compatible, local)
   ▼                                    │                                 ├─► Sandbox (no network; builds, tests, renders previews)
Object storage (MinIO / S3) ◄───────────┴─────── file processing ────────┘
```

- **API**: authentication, authorization, workspaces, review actions, collaboration posts, Studio, uploads. It never runs AI work inline.
- **Worker**: claims jobs from a PostgreSQL queue (`FOR UPDATE SKIP LOCKED`), runs orchestration steps, file extraction and sandbox jobs. Each step is idempotent and resumable (D4).
- **Sandbox**: unchanged isolation (no network, read-only root, separate user). Extended to lint, type check, integration tests and preview rendering.
- **Object storage**: uploads, large artifacts, previews and evidence (D5).

## 2. Backend modules and boundaries

| Layer | Modules | May call |
|---|---|---|
| Identity and tenancy | auth, organizations, permissions, projects | Database only |
| Governance | workflows (engine, compiler, state machine), approvals, reviews, sensors, hooks, rules, audit | Identity; never providers |
| Execution | orchestration, agents, providers, routing, context, tools, sandbox client | Governance through engine commands only |
| Content | artifacts, files, knowledge, requirements, traceability | Identity, storage |
| Collaboration | channels, messages, handoffs, decisions, escalations, notifications | Identity, content references |
| Experience | intake, workspaces, portal API, Studio API, admin observability | All of the above through service interfaces |

Rules: only the engine writes stage state; only the approval service writes approval records; execution modules produce artifacts and messages but cannot transition stages; every cross-tenant read is filtered by organization and project.

## 3. Request and execution flow

1. A human action (confirm intake, approve, request changes) is validated and committed by the API.
2. The engine records the transition and enqueues the next job in the same transaction.
3. The worker runs the job: select specialist, build context, call the provider, persist an artifact version, run sensors, dispatch the independent review, build the review package, notify the assigned professional.
4. The stage waits at its gate until a valid human decision arrives.

## 4. Technology

Kept: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL 16, React 18, TypeScript, Vite, React Flow, Playwright, pytest, Docker Compose. Added: MinIO, Tailwind (D6), a text-extraction stack for files (pypdf, python-docx, openpyxl, python-pptx; OCR with Tesseract inside the processing container). No Redis unless the queue proves insufficient.

## 5. Observability

Every request and job carries a correlation ID through logs, audit events, agent executions, sensor runs and notifications. Administrators get execution traces, costs and failures. Ordinary users never see prompts, provider details or raw tool output.
