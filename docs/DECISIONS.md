# Decision Log

Format: each decision has context, decision, consequences, and status. New decisions are appended; superseded decisions stay with status `Superseded by ADR-xxx`.

## ADR-001: Build independently, use the AWS reference for concepts only
- Status: Accepted (2026-11-18)
- Context: awslabs/aidlc-workflows is MIT-0 licensed and is a developer-harness framework, not a multi-tenant server.
- Decision: Re-implement concepts (compiled stage definitions, engine-owned transitions, independent reviewers, sensors, scopes, audit-first writes). Do not copy source or prose. Clone kept outside the repository at `C:\Users\vyshu\Desktop\aidlc-reference-research`.
- Consequences: More design work up front; clean provenance; the reference is cited in `docs/research/`.

## ADR-002: Server-side enforcement only
- Status: Accepted
- Context: The reference enforces guards through host hooks, which depend on the developer's harness and can be disabled by policy.
- Decision: All authority (state transitions, approvals, permissions, tool grants) is enforced in the backend, with DB constraints where feasible. The frontend and host hooks are conveniences only.
- Consequences: Requires a backend service and database from the start; no shortcuts in the UI.

## ADR-003: Python 3.13 + FastAPI + SQLAlchemy 2 + Alembic + PostgreSQL
- Status: Accepted
- Context: Environment has Python 3.13.14 and Docker 29.5. Team brief lists Python, FastAPI, Pydantic, SQLAlchemy and PostgreSQL.
- Decision: Adopt these. Use Pydantic v2 for all API and LLM-output schemas.
- Consequences: Typed contracts across API and provider layer; async I/O for provider calls.
- Alternatives rejected: Node/TS backend (weaker DB constraint tooling for our needs), Django (heavier, less typed API), LangChain (hides control we need for schema, cost and audit).

## ADR-004: DB-backed job queue before Redis or Celery
- Status: Accepted
- Context: Need durable background work tied to state transitions. Adding Redis and a broker adds operational surface.
- Decision: `jobs` table, enqueued in the same transaction as the state change, claimed with `SELECT ... FOR UPDATE SKIP LOCKED`, with leases and idempotency keys.
- Consequences: Simpler deployment, transactional consistency for enqueue. Throughput limit to be measured in M10. Revisit Temporal or Celery+Redis only with measured need.

## ADR-005: React + TypeScript + Vite + Tailwind + TanStack Query
- Status: Accepted
- Context: Authenticated enterprise app; no SEO requirement.
- Decision: Vite SPA. React Flow for the Workflow Studio canvas. Radix primitives for accessibility.
- Consequences: No server rendering. Need a clear client-side route guard that is never the only authorization check.

## ADR-006: Provider abstraction in-house, official SDKs underneath
- Status: Accepted
- Context: Need schema-preserving fallback, cost tracking and audit that generic frameworks hide.
- Decision: Own `ProviderAdapter` protocol; adapters wrap official SDKs (Anthropic, OpenAI, Google GenAI) and an OpenAI-compatible HTTP client for other servers.
- Consequences: Adapter maintenance per vendor; contract tests per adapter.

## ADR-007: Approvals are human-only and version-bound
- Status: Accepted
- Context: Brief requires that the LLM never decides approval and that approvals do not survive artifact changes.
- Decision: `approval_decisions` store artifact version and content hash; DB CHECK on human principals; new versions supersede prior approvals; invalidation propagates via `consumes` edges in the same transaction.
- Consequences: More bookkeeping; clear audit story.

## ADR-008: Tamper-evident audit via hash chain (not a blockchain)
- Status: Accepted
- Context: Reference audit is not tamper-evident. Enterprise customers need evidence integrity.
- Decision: Per-organization append-only chain of SHA-256 hashes plus periodic signed checkpoints; DB role separation.
- Consequences: Chains serialize writes per organization. Mitigate with per-organization partitions and short transactions. Measure in M10.

## ADR-009: Single core, two experiences (internal console and owner portal)
- Status: Accepted
- Context: The brief requires a separate presentation and interaction layer without a second orchestrator.
- Decision: Portal API is a separate route prefix with its own response models, calling the same domain services and engine commands.
- Consequences: Strict response models and tests for forbidden fields. No duplicate workflow logic.

## ADR-010: Mock provider for CI, live providers opt-in
- Status: Accepted
- Context: CI must be deterministic and must not spend money or depend on external services.
- Decision: Deterministic mock adapter drives all default tests. Live tests are marked and run manually or nightly with a budget cap. The current environment has no provider credentials configured, so live tests have not been run.
- Consequences: Live integration is not verified until keys are supplied (see `KNOWN_ISSUES.md`).

## ADR-011: Project folder gets its own git repository
- Status: Accepted (2026-11-18)
- Context: `C:\Users\vyshu\Desktop\Proj1` sat inside the user's home-directory git repository (root `C:/Users/vyshu`, which has no commits).
- Decision: `git init -b main` inside `Proj1`. No commits yet; the user has not asked for commits.
- Consequences: Commits from this project do not land in the home-directory repository. The home repository's untracked files are not our concern.

## ADR-012: Reviewer assignment is per project membership (answers Q-1)
- Status: Accepted (2026-11-18)
- Decision: Approval slots are filled by people with a project role on that project. Org admins assign project members. Org-wide reviewer roles are not used for approvals.

## ADR-013: Owners cannot download source code by default (answers Q-2)
- Status: Accepted (2026-11-18)
- Decision: Source download is off for owners. An org admin can enable it per project. Enabling it is an audited permission change.

## ADR-014: Documented deployment only in the first release (answers Q-4)
- Status: Accepted (2026-11-18)
- Decision: M10 produces deployment docs verified on a clean local machine. No cloud account or paid infrastructure is created.

## ADR-015: Self-signup with email verification and a personal organization (answers Q-9, revises the earlier admin-created default)
- Status: Accepted (2026-11-18)
- Decision: Users register with email and password, verify their email, and receive a personal organization in which they are admin and Project Owner. Joining an existing organization still requires an admin invite. Consequences: email verification and abuse protection (rate limits, CAPTCHA-free throttling, disposable-email policy) move into M2 scope; the signup flow is a new threat surface for the security catalogue in TEST_STRATEGY.md.

## ADR-016: No live provider keys yet; mock provider only (answers Q-3)
- Status: Accepted (2026-11-18)
- Decision: All tests use the deterministic mock provider. Live tests stay disabled until keys and a budget are provided.

## ADR-017: Design prototypes are real runnable front-end code from the start (answers Q-5, revises the earlier static-preview default)
- Status: Accepted (2026-11-18)
- Decision: The UI/UX stages generate runnable front-end code. Consequences: the design stage needs the sandbox from SECURITY_ARCHITECTURE.md section 7 before M6; previews run in an isolated origin with no access to backend cookies or APIs; generated code passes the same sensors as development code (lint, type check, dependency audit, secret detection). The milestone order is unchanged, but M6 scope grows and the portal's design section must show the running preview rather than static images.

## ADR-018: GitHub is the code host (answers Q-8)
- Status: Accepted (2026-11-18), blocked on tooling
- Decision: The project repository will be hosted on GitHub. Blocker: the GitHub CLI is not installed, and the GitHub connector failed to authenticate in this session. The user must fix the connection before the repo is pushed. Nothing was pushed.

## ADR-019: Retention defaults (answers Q-6)
- Status: Accepted (2026-11-18)
- Decision: Audit records of approvals and permission changes are kept 7 years. Conversations are kept 2 years. Uploads are kept 1 year. Each organization can configure these values.

## ADR-020: SOC 2 is the first compliance knowledge pack (answers Q-7)
- Status: Accepted (2026-11-18)
- Decision: The compliance agent's first knowledge pack covers SOC 2 controls. It is added in M7 with the knowledge system.
