# Repository Audit

Date: 2026-11-19. Scope: the whole `Proj1` working tree, including uncommitted work, measured against the Master Rebuild Prompt.

## 1. What the repository is

A modular monolith: a FastAPI backend, a Vite and React frontend, PostgreSQL, and a separate sandbox container, run with Docker Compose.

| Area | Location | Size | Notes |
|---|---|---|---|
| Backend API | `backend/app` | about 9,900 lines across 20 modules, 81 HTTP routes | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, pg8000 |
| Database | `backend/migrations/versions` | 13 migrations (0001 to 0013) | Append-only triggers on audit, decisions, versions and evidence |
| Frontend | `frontend/src` | about 3,200 lines, 9 routes | React 18, TypeScript, react-router, React Flow, plain CSS (no Tailwind) |
| Sandbox | `sandbox/runner.py`, `infrastructure/docker/sandbox.Dockerfile` | 1 runner | No network, read-only root, dropped capabilities, separate code user |
| Tests | `backend/tests`, `tests/e2e`, `tests/security` | about 250 backend test functions, 6 browser specs, 1 sandbox attack probe | pytest with an embedded PostgreSQL; Playwright with Chrome |
| Docs | `docs/` | 13 design docs, 8 research docs, 1 operations record | Written during milestones M1 to M9 |

Git: `main` at `2edb725` (Milestone 8). The Milestone 9 portal, the shared-organization remake and the sandbox (66 changed or new files) are **not committed**.

## 2. Backend modules

| Module | Purpose | State |
|---|---|---|
| `auth` | Signup, email verification, login, sessions, CSRF, rate limits | Works. Email goes to an outbox table only |
| `organizations` | Organizations, memberships, invitations, confirmed roles, professional profiles held per person | Works. Shared-organization mode with admin confirmation |
| `projects` | Projects and project members | Works |
| `workflows` | State machine, compiler, versioned definitions, execution, stage runs | Works. Sequential only; conditions and parallel stages are refused |
| `artifacts` | Versioned artifacts with SHA-256 | Works. JSON content only, no files |
| `approvals` | Policies (single, any, all, role-based, sequential), version-bound decisions, invalidation, change requests | Works |
| `providers` | Anthropic, OpenAI, Gemini, OpenAI-compatible and mock adapters; encrypted keys; routes with fallback | Works. No streaming, no tool calling |
| `agents` | Agents, immutable versions, lineage independence, context manifests, reviewer runs | Works. One lead per stage, one reviewer per profile |
| `skills` | Versioned skills, stage limits, pinned dependencies | Works |
| `sensors` | 18 deterministic sensors, evidence, risk acceptance | Works. Code checks rely on recorded evidence or the sandbox |
| `hooks` | Declarative hooks with three built-in actions | Works |
| `rules` | Hierarchical rules, governed proposals, learning from corrections | Works |
| `studio` | Workflow drafts, publishing, import and export, catalog | Works |
| `portal` | Owner intake, workspace, deliverables, messages, test reports, triage, AWS-based 33-stage lifecycle | Works, uncommitted |
| `bootstrap` | Seeds workflows, makes the shared organization, connects local AI | Works, uncommitted |
| `sandbox_client` | Sends generated files to the sandbox and records real results | Works in tests, uncommitted |
| `audit`, `notifications` | Hash-chained audit, per-user notifications | Works |
| `api`, `profiles`, `stages`, `tools` | Planned in M1 | Empty folders |

## 3. Frontend

Routes: sign-up, email verification, sign-in, accept invitation, notifications, Studio, Team, home, project.

- Home creates projects and lists reviews waiting for the signed-in person.
- The project page is one generic portal with five tabs (overview, brief, deliverables, conversations, testing).
- Studio holds the visual workflow builder, profiles, agents, rules, hooks, sensors and AI settings.
- There are no profile workspaces, no team collaboration area, no file upload, no artifact editor, no audit or observability screens, and no visual design viewer.

## 4. Verified behaviour

- Before this audit: 349 backend tests passed, 20 browser tests passed, and 34 deliberate safeguard breakages were run with 31 caught (the 3 gaps were then covered by new tests).
- A full six-profile run on the local `qwen3-vl:4b-instruct` model passed for the earlier 6-stage lifecycle. The 33-stage lifecycle has **not** had a live run.
- The sandbox passed an attack probe: no network, no access to jobs or results, read-only root, no root, capped processes, stopped endless loops and output, rejected unsafe paths, and real Python and JavaScript projects built and tested.
- Audit test run (2026-11-19): see `TEST_RESULTS.md`. An orphaned test database from the interrupted session had to be stopped first.

## 5. Gaps against the rebuild prompt

| Prompt requirement | Current state | Gap |
|---|---|---|
| Six departments with many specialist agents each | One lead agent per stage plus one reviewer per profile | No named specialists per department, no multi-agent stages |
| Per-department stage lists (prompt Part II) | The AWS 33-stage, 5-phase lifecycle | Different stage set (see `REBUILD_PLAN.md`, decision D1) |
| Human Professional Review and User Review and Approval stages | Only profile holders approve; the owner can only request changes | User approval removed in the last remake (decision D2) |
| Multiple reviewers per profile, primary and backup, project assignments, workload, escalation, reassignment | One flat "holds profile" record per person and organization | Missing |
| Review actions: escalate, add finding, comment, edit artifact, reassign | Approve, request changes, reject only | Missing |
| Review packages bound to approvals | Approvals bind to artifact version and keep a validation snapshot | No review package entity |
| Team collaboration hub (six channel types, handoffs, decisions, disagreement escalation, human participation) | None. Agents never talk to each other | Missing entirely |
| Orchestration with durable execution, recovery and correlation IDs | Runs as an in-process background task after each request | A restart loses work; no queue or worker |
| Streaming and tool calling | Not implemented | Missing |
| Context retrieval layer | Brief plus the nearest five approved deliverables, cut to 2,000 characters | No retrieval, no files |
| File and knowledge management (uploads, extraction, OCR, provenance) | None | Missing entirely |
| Profile workspaces (BA, Architect, visual Designer, Developer, QA, DevOps) | One generic project page | Missing |
| Visual design artifacts, prototypes, previews | Written design text only | Missing |
| QA running the actual application, evidence, screenshots | Unit tests of generated code in the sandbox | No running application, no integration or end-to-end tests of generated software |
| Deployment and verification | Written plans only | No real deployment target |
| States UNDER_REVIEW, AWAITING_USER_INPUT, AWAITING_APPROVAL | AWAITING_HUMAN_REVIEW covers them | Missing finer states |
| Parallel and conditional stages | Refused by the compiler | Missing |
| Admin observability and audit search | Audit is stored; no screens | Missing |
| Object storage | None | Missing |
| Tailwind and a component system | Plain CSS tokens | Prompt default not adopted |

## 6. Simulated, placeholder or legacy behaviour

- The mock provider adapter is a deterministic test double. It is labelled "Offline test connection" and used for browser tests. It must never be a default for real use.
- The three Initialization steps run trivial deterministic functions that only copy project details. They do not inspect a workspace.
- `intake_summary`, `requirements_outline` and the `discovery-foundation` template are Milestone 3 demonstration pieces.
- Owner message routing uses fixed keyword rules, not a model.
- Several stages (deployment, environment provisioning, performance validation) only write plans and say so.
- The "personal" signup mode exists so older tests keep their one-organization-per-account setup.
- 40 `.gitkeep` files, 16 of them in folders that were never used.

## 7. Security observations

- Good: allow-listed owner responses, CSRF, HttpOnly sessions, Argon2id, encrypted provider keys, tenant checks, append-only audit and decisions, sandbox isolation, generated code results that cannot be overridden by hand.
- Risk: long-running AI work runs inside the API process. A crash or restart can leave a stage half-done.
- Risk: the API and the sandbox share a job volume. The API container runs as root.
- Risk: rate limits are per process and in memory.
- Note: the local `.env` contains the bootstrap administrator's email. It is git-ignored.
- Missing: file upload scanning, dependency scanning in CI, backup and restore, observability.

## 8. Reusable foundations

Engine, compiler, approvals, artifacts, providers, agents, skills, sensors, hooks, rules, audit, studio, sandbox and the tenant model are tested and sound. The rebuild should extend them, not replace them (decision D3).
