# Master Plan

Status: Proposed (Milestone 1). Dates are not committed; each milestone is sized to be completed and verified before the next starts.

## Milestones and exit criteria

| # | Milestone | Scope | Exit criteria (all must hold) |
|---|---|---|---|
| M1 | Research and architecture | Reference research (8 docs), architecture set, data model, state machine, approval design, security model, portal design, repo skeleton, roadmap | **Current milestone.** All docs present; no unresolved contradiction between documents; open questions listed in `KNOWN_ISSUES.md` |
| M2 | Application foundation | Backend skeleton (FastAPI, config, logging, error model), PostgreSQL + Alembic, Docker Compose, frontend skeleton (Vite, routing, auth screens), identity (password + sessions + CSRF), organizations, users, memberships, projects, project members, owner role, authorization base classes, audit chain (write and verify), CI test pipeline locally | A user can log in, create an organization and create a project; cross-tenant negative tests pass; audit chain verifies; migrations apply on an empty database |
| M3 | Workflow engine | Profiles and stages as versioned definitions, workflow versions, compiler with all checks, stage state machine, transactional transitions, optimistic locking, phase and workflow derivation, deterministic (no-AI) execution with stub stages | A deterministic workflow executes end to end without AI; every legal and illegal edge tested; compiler rejects each invalid class in fixtures |
| M4 | Human approval engine | Approval policies (six types), approval decisions, risk acceptance, change requests, version binding, supersession, invalidation propagation, comments, rework loop with max-loop guard, concurrency and replay protections | No protected stage can advance without a valid approval; approval for V does not satisfy V+1; atomicity test passes; security catalogue items for approvals pass |
| M5 | AI provider layer | Adapter protocol; Anthropic, OpenAI, Gemini, OpenAI-compatible, local; secrets (envelope encryption); model routes; fallback; health checks; token and cost tracking; admin test UI | The same stage executes with different providers (mock in CI; live verified only if keys are supplied); no key appears in any response, log or audit scan |
| M6 | Agent orchestration | Agent configurations (versioned), profile configurations, skills, tool registry and grants, lead/support/reviewer runs, context manifests, structured handoffs, reviewer independence enforcement, representative templates | Multiple profiles execute independently; reviewer self-review refused by test; agent cannot call tools outside grant |
| M7 | Hooks, sensors and rules | Event bus, hook engine (declarative, fail-closed for mandatory), sensor registry with the 16 initial sensors from the brief, rule hierarchy with versions, governed learning loop with proposals | Mandatory validations block gates; hooks run at configured events; rule inheritance tested; AI cannot activate a rule or hook |
| M8 | Workflow Configuration Studio | Profile editor, stage editor, visual workflow builder (React Flow), permission editor, rules editor, hooks and sensors editor, import/export JSON/YAML | An administrator builds and publishes a custom profile with a custom stage and gate without code changes; invalid configurations cannot publish |
| M9 | Complete default lifecycle + User Portal | Six default profiles fully configured; intake and confirmation; owner workspace; design and QA participation; notifications; pending actions; owner approvals; message routing | A project progresses through all six profiles with real providers (live run recorded) and persisted deliverables, with mandatory human gates; owner acceptance criteria 1–20 in `USER_PORTAL.md` section 16 pass |
| M10 | Production hardening | Full security testing, performance tests, observability (metrics, traces), backup and restore drill, deployment documentation, data retention jobs, dependency and secret scans in CI | Production-readiness assessment written with evidence; documented deployment steps followed on a clean machine |

## Dependencies

- M2 blocks everything.
- M3 blocks M4, M6, M7, M8.
- M4 blocks owner approvals in M9.
- M5 blocks M6 (agents need providers) and M9 with live runs.
- M7 blocks M8 editors (editors configure what exists).
- M9 needs M4, M5, M6, M7 and the portal groundwork in M2–M4.

## Immediate next steps (Milestone 2 start)

1. Inspect the repo again and confirm the M1 document set (done as part of M1 exit).
2. Write `docker-compose.yml`, `backend/pyproject.toml` (uv), `frontend/package.json` (pnpm), config and logging.
3. First Alembic migration: organizations, users, sessions, memberships, projects, project_members, audit_events (append-only trigger).
4. Tests first for tenant isolation and audit chain.
5. Frontend login, organization creation and project creation screens bound to real APIs.
6. Development-time Claude Code assets under `.claude/` (subagent definitions, skills, hooks). These are written after the backend tests exist so that they can be verified.

## Development rules for every milestone

- Start with inspection of existing code, missing parts, dependencies, risks, and a written plan in `IMPLEMENTATION_STATUS.md`.
- Small modules; run tests after each module.
- Update docs in the same change as the code.
- Milestone close: run tests, security review, verify exit criteria, list remaining issues in `KNOWN_ISSUES.md`.
