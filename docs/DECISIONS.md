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

## ADR-021: Dev and test on Python 3.12 with pure-Python PostgreSQL driver (Milestone 2)
- Status: Accepted (2026-11-19), supersedes the 3.13 target for the local venv only
- Context: `pgserver` (embedded PostgreSQL for tests) has no cp313 wheel. Python 3.13 was the target in ADR-003.
- Decision: `requires-python >= 3.12`; the local venv uses 3.12.13. The application code avoids 3.13-only features and should run on 3.13. Re-test on 3.13 before M10.
- Driver: `pg8000` (pure Python) replaces `psycopg[binary]`, because Windows Application Control blocks the psycopg native DLL in this environment. Production may switch to psycopg 3 once the policy allows it; SQLAlchemy URLs differ only in the driver name.

## ADR-022: Windows Application Control workarounds in the local environment
- Status: Accepted as a local workaround (2026-11-19)
- Context: The policy blocks some compiled extensions from site-packages: SQLAlchemy `.pyd` speedups, psycopg binaries, and the native rollup binary.
- Decision: Remove the blocked SQLAlchemy `.pyd` files from the local `.venv` only (SQLAlchemy falls back to its pure-Python modules). For rollup, npm `overrides` points `rollup` at `@rollup/wasm-node`, the official WebAssembly build with the same API. Both are environment workarounds. Neither is a product decision, and both should be reverted when the policy allows native modules.
- Consequence: Production builds are expected to use the native rollup and SQLAlchemy extensions. The wasm override applies to every install, so it should be revisited before release.

## ADR-023: Milestone 2 security choices
- Status: Accepted (2026-11-19)
- Decision:
  - Session cookie is opaque, HttpOnly, SameSite=Lax; the server stores only its SHA-256.
  - CSRF token is HMAC(secret, session token), so it needs no storage. Required on every mutating request.
  - Passwords: Argon2id, minimum 12 characters.
  - Login lockout after 5 failures for 15 minutes; unknown and wrong-password responses are identical; timing is equalized.
  - Signup returns the same response whether or not the email exists.
  - Not-found and not-permitted are indistinguishable (404) for tenant resources.
  - Audit chain: one chain per organization plus a platform chain. Appends lock the chain row. A trigger blocks UPDATE and DELETE.
- Known gaps: rate limiter is per process; no MFA yet; no session-idle timeout beyond the absolute TTL.

## ADR-024: Stage transitions are the only writer of stage state; execution locks first (Milestone 3)
- Status: Accepted (2026-11-19)
- Decision: Every transition locks the execution row, then the stage row, inside one transaction. The log row, the audit event and the readiness update commit together. Lock order is fixed to avoid deadlocks.
- Consequence: Transitions in one execution are serialized. That is acceptable at current scale. Revisit if one execution holds many parallel stages.

## ADR-025: APPROVED is refused until the approval engine exists (Milestone 3)
- Status: Accepted (2026-11-19)
- Decision: The state machine defines the human-only edges, but the engine refuses APPROVED with `approval_required` until Milestone 4 provides the approval records that must exist first. Downstream stages therefore cannot start in M3. This is intentional: nothing may advance without an approval.

## ADR-026: Stage work is deterministic code, not AI, in this milestone (Milestone 3)
- Status: Accepted (2026-11-19)
- Decision: Stages name a registered pure function (`app/workflows/work.py`). Its output must contain the stage's required keys, or the stage is BLOCKED. A raised exception moves the stage to FAILED and records the exception type. Real AI-backed work arrives with the provider layer (Milestone 5).

## ADR-027: Compiler rejects what it cannot run (Milestone 3)
- Status: Accepted (2026-11-19)
- Decision: Conditional and parallel execution are refused with explicit messages, not silently ignored. Unknown fields are refused. Stage ids are lowercase snake_case, 1 to 64 characters.

## ADR-028: Approval counts are scoped to a version and an approval epoch (Milestone 4)
- Status: Accepted (2026-11-19)
- Decision: A decision counts only when its artifact version is the current one and its epoch equals the stage's epoch. Invalidation bumps the epoch instead of editing rows. Decisions are append-only.
- Consequence: History is kept, and invalidation needs no row updates. The unique index for one approval per approver includes the epoch so a person can approve again after invalidation.

## ADR-029: Stages without a policy use a single project-owner approval (Milestone 4)
- Status: Accepted (2026-11-19)
- Decision: Every stage ends in a human gate. A missing `approval_policy` means `single` with role `project_owner`. Policies are validated at compile time.

## ADR-030: Artifact content is stored in Postgres JSONB for now (Milestone 4)
- Status: Accepted as an interim choice (2026-11-19)
- Decision: Versions store canonical JSON with a SHA-256. ADR-004 and the architecture still call for object storage for large artifacts. That move is tracked in KNOWN_ISSUES and will not change the version or hash model.

## ADR-031: Only the engine can approve a stage (Milestone 4)
- Status: Accepted (2026-11-19)
- Decision: `transition_stage` refuses APPROVED unless the approval service passes `approval_satisfied=True` after it has checked the policy in the same locked transaction. Approval rows are human-only at the database level.

## ADR-032: Vendors are reached through our own adapter contract (Milestone 5)
- Status: Accepted (2026-11-19)
- Decision: Each vendor gets one small adapter that builds documented HTTP requests. No general AI framework. Normalized errors and usage come out of the adapter; nothing else knows vendor formats.
- Consequence: We own the request and response code and must update it when vendors change their APIs. Contract tests with mocked HTTP guard the shapes we rely on.

## ADR-033: Credentials use AES-256-GCM envelope encryption with bound associated data (Milestone 5)
- Status: Accepted as an interim scheme (2026-11-19)
- Decision: The key-encryption key comes from `AIDLC_SECRET_ENCRYPTION_KEY` (32 bytes, base64). Development and test derive a key from the signing key so local runs work; production refuses to start without it. Associated data binds each ciphertext to its organization and name. Only ciphertext, nonce, key version and last four characters are stored.
- Consequence: Data-key envelopes and a KMS integration are still to come. Rotation is supported by key version fields but no re-encryption job exists yet (KNOWN_ISSUES M5-4).

## ADR-034: Provider calls run synchronously inside the stage transaction (Milestone 5)
- Status: Accepted for now (2026-11-19)
- Decision: A stage's AI call runs inside the locked transaction that records its result, so run records, usage, audit and the transition commit together. This holds row locks during network calls.
- Consequence: Long vendor latency holds locks on that stage's execution. Move AI calls to a worker with a lease when the queue exists (ADR-004, KNOWN_ISSUES M5-1).

## ADR-035: Cost is reported only for models with an entered price (Milestone 5)
- Status: Accepted (2026-11-19)
- Decision: The price table is empty by default. Tokens are always recorded; cost is computed only for an exact (adapter, model) price. No vendor price is assumed in code.
- Consequence: Cost reports are blank until an administrator or a maintained price file supplies prices.

## ADR-036: Fallback happens per candidate, with one schema repair (Milestone 5)
- Status: Accepted (2026-11-19)
- Decision: The candidate list is primary then fallbacks. A retryable error retries on the same candidate with backoff. Other errors move to the next candidate. Output that fails the schema gets one repair attempt on the same candidate before moving on. Every attempt is an AgentRun row.
- Consequence: Retries can spend budget. Budgets and per-organization limits are still to come (KNOWN_ISSUES M5-5).

## ADR-037: Profiles group agents; agents are versioned and immutable (Milestone 6)
- Status: Accepted (2026-11-19)
- Decision: A profile is a professional area. An agent belongs to one profile and changes only through new versions. Runs point at the version they used.

## ADR-038: Reviewer independence is enforced by lineage at run time (Milestone 6)
- Status: Accepted (2026-11-19)
- Decision: Each agent carries a lineage root. A clone shares its source's root. The compiler refuses a stage whose reviewer names the lead. The runner refuses a reviewer that shares the lead's root, so a clone cannot review its own work.

## ADR-039: Context is passed per source, never by default (Milestone 6)
- Status: Accepted (2026-11-19)
- Decision: A version lists its context sources. A lead may read project input and feedback; a reviewer may read only the artifact. Prompts are built from those sources alone. Run manifests record ids and counts, not content.

## ADR-040: Reviews are advisory until sensors exist (Milestone 6)
- Status: Accepted as an interim rule (2026-11-19)
- Decision: A reviewer's verdict and findings are recorded and shown to the owner, but they do not change the gate. Blocking reviews come with the sensor framework (M7), where deterministic checks decide, not a model's own judgement.

## ADR-041: Agent versions pin skill versions (M6 follow-up)
- Status: Accepted (2026-11-19)
- Decision: Creating an agent version resolves each named skill to its latest version and stores the key and version. Runs read exactly that version.
- Consequence: A skill edit reaches an agent only through a new agent version, so behaviour never changes silently. Skills do not grant tools; the agent must already hold them.

## ADR-042: Fallback is an agent-version setting (M6 follow-up)
- Status: Accepted (2026-11-19)
- Decision: `allow_fallback` defaults to true. When false, the run uses only the route's primary provider. This keeps a reviewer on its configured provider at the cost of failing the stage when that provider is down.

## ADR-043: Sensors about code and security read evidence, not artifacts (Milestone 7)
- Status: Accepted (2026-11-19)
- Decision: An AI could write "tests passed" into its own output, so these sensors ignore artifact content. They read evidence recorded by an authorized person and report ERROR without it.
- Consequence: They fail closed until someone records a result. The sandbox or a CI integration should supply this evidence later.

## ADR-044: NOT_APPLICABLE does not satisfy a mandatory sensor (Milestone 7)
- Status: Accepted (2026-11-19)
- Decision: Otherwise an artifact could avoid a check by leaving out what the check reads. If a check truly does not apply, it should not be mandatory on that stage.

## ADR-045: Hooks are declarative and fail_closed must be enforceable (Milestone 7)
- Status: Accepted (2026-11-19)
- Decision: Hooks choose from built-in actions and cannot run code. Only events the platform emits are accepted. fail_closed is allowed only at points where the engine can stop the operation.
- Consequence: Hook timeouts are measured after an action returns; they do not interrupt it. Actions are short database operations today.

## ADR-046: A workflow keeps the configuration it started with (Milestone 7)
- Status: Accepted (2026-11-19)
- Decision: Starting a workflow records agent versions, rule versions and teams. Hooks are the exception: they stay live, so an organization can add a control to running work.

## ADR-047: Rules guide agents; sensors and hooks enforce (Milestone 7)
- Status: Accepted (2026-11-19)
- Decision: A rule is text given to a model. Marking it mandatory stops lower levels from redefining it, but it cannot force a model to comply. Anything that must hold is expressed as a sensor or hook.

## ADR-048: People join an organization by single-use, email-bound invitation
- Status: Accepted (2026-11-18)
- Decision: Only organization admins invite. The token is stored as a SHA-256 hash, expires after 7 days, works once, and can be accepted only by a signed-in account with the invited email. An invitation can also grant one project role.
- Consequence: A forwarded link is useless to anyone else. New users must create and verify an account with that address first.

## ADR-049: Nobody changes their own access, and every project keeps an owner
- Status: Accepted (2026-11-18)
- Decision: Admins cannot change or remove their own organization or project access. Removing someone from an organization also removes their project roles in it. A change that would leave a project without an owner is refused.
- Consequence: A person cannot make themselves a reviewer of their own work. Leaving an organization needs another admin.

## ADR-050: Organizations own their workflows; drafts become immutable versions only by publishing (Milestone 8)
- Status: Accepted (2026-11-18)
- Decision: A workflow belongs to one organization or is a platform template. Drafts may be invalid and carry a revision so edits cannot overwrite each other. Only an organization admin can publish, and publishing checks the compiler plus the organization's own profiles, agents, model routes and stage outputs. A project can start only its organization's workflows or platform templates.
- Consequence: Every stage still ends at a human gate; the Studio chooses who approves but cannot remove the gate.

## ADR-051: Imported workflows are data and always land as drafts (Milestone 8)
- Status: Accepted (2026-11-18)
- Decision: JSON and YAML imports are size limited. YAML uses the safe loader and refuses aliases. An import never publishes anything.

## ADR-052: The diagram edits the same dependencies as the form (Milestone 8)
- Status: Accepted (2026-11-18)
- Decision: React Flow draws `depends_on` and edits it by dragging; form checkboxes edit the same field. No position data enters the workflow definition, so a layout change cannot change a published hash.
