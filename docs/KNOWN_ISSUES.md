# Known Issues, Risks and Open Questions

Status as of Milestone 1 (2026-11-18). No application code exists yet.

## Open questions (need the product owner's decision)

| ID | Question | Our proposed default | Why it matters |
|---|---|---|---|
| Q-1 | Who are the "internal human reviewers" and how are they assigned: per project or per organization role? | Per project membership with a role; org admins assign | Determines approval slots and RBAC tables |
| Q-2 | Should Project Owners be allowed to download source code? | No by default; configurable per project | Affects Deliverables and release scope |
| Q-3 | Which AI provider keys will be available for live testing, and what monthly budget? | None configured yet; live tests stay off until keys and a budget exist | Live integration cannot be verified without them |
| Q-4 | Is deployment to a customer cloud required in the first release, or only documented? | Documented only (brief Part 27 accepts "documented deployment") | Scope of M10 |
| Q-5 | Are design prototypes generated as real front-end code or as static previews? | Static, sandboxed previews first; code later | Affects sandbox and preview design |
| Q-6 | Retention periods for audit, conversations and uploads? | Placeholder: audit 7 years for approvals and permission changes; conversations 2 years; uploads 1 year; configurable per org | Compliance; affects schema and jobs |
| Q-7 | Which regulated frameworks must be supported first (for compliance agent knowledge)? | None until a customer names one | Scope of knowledge packs |
| Q-8 | Is GitHub the code host for this project? | Assumed, but not connected. GitHub CLI is not installed and the GitHub MCP connector failed with an authorization-header error in this session | CI setup and PR flow depend on it |
| Q-9 | Do owners need an email-based invite flow in M2, or only admin-created accounts? | Admin-created accounts first | Auth scope |

## Risks

| ID | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R-1 | Scope is very large (six profiles, studio, portal, providers, hooks, sensors, rules). Quality could slip if built all at once | High | High | Milestones with exit criteria; no profile goes live without its gates and tests |
| R-2 | LLM output quality varies; artifacts may be weak even when gates pass | High | Medium | Sensors, independent reviewers, human approval; fail closed |
| R-3 | Prompt injection through uploads and owner messages | High | High | Untrusted-input handling, least-privilege grants, injection test corpus |
| R-4 | Hash-chained audit serializes writes per organization | Medium | Medium | Short transactions, measure in M10, partitioning if needed |
| R-5 | Model-based classifier mis-routes owner messages | Medium | Medium | Validation layer, clarifying questions on low confidence, reclassification audited |
| R-6 | Visual workflow studio complexity | Medium | Medium | Ship form-based editor first, then canvas; compiler is the source of truth |
| R-7 | Provider API changes and SDK churn | Medium | Low | Adapter contract tests; pin SDK versions |
| R-8 | Reference repository changes after our snapshot | Low | Low | Snapshot recorded in `docs/research/REFERENCE_ARCHITECTURE.md` |
| R-9 | The project is not yet a git repository with commits; work could be lost if the folder is moved or cleaned | Medium | Medium | Initialize repo (done); commit milestone snapshots when the user agrees |

## Known gaps in the current state

- **No code exists.** Only documentation and an empty directory skeleton with `.gitkeep` files. Nothing runs.
- **Reference research is from a shallow clone** of the default branch at commit `d52a31cb`; we did not run the reference's test suite.
- **Reference license** is MIT-0. We do not copy code or prose; if that changes, revisit `REUSABLE_CONCEPTS.md`.
- **No provider credentials** are configured. None were requested or stored.
- **Development-time Claude Code assets** (subagents, skills, hooks under `.claude/`) are directories only. They are planned for Milestone 2, after the foundation exists to test against.

## Items deliberately deferred

- Kubernetes, Kafka, Redis, Temporal, vector database, microservices (see `ARCHITECTURE.md` section 3).
- SSO (OIDC/SAML), MFA enrollment flows (M10 or on customer request).
- Live provider calls in CI.

## Answers received (2026-11-18)

| ID | Answer | Effect |
|---|---|---|
| Q-1 | Reviewers are assigned per project membership | ADR-012 |
| Q-2 | No source download for owners by default; admin can enable per project | ADR-013 |
| Q-3 | No keys yet; mock provider only | ADR-016 |
| Q-4 | Documented deployment only | ADR-014 |
| Q-5 | **Real runnable code for prototypes from the start** (changed from the proposed default) | ADR-017; sandbox moves into M6 scope |
| Q-6 | Proposed retention defaults | ADR-019 |
| Q-7 | SOC 2 first | ADR-020 |
| Q-8 | GitHub. Blocked: CLI not installed, connector failed auth | ADR-018; open blocker |
| Q-9 | **Self-signup with email verification and personal org** (changed from admin-created default) | ADR-015 |

Still open: the GitHub connection (Q-8) must be fixed before the repo can be created there.

## Milestone 2 known issues (2026-11-19)

| ID | Issue | Impact | Plan |
|---|---|---|---|
| M2-1 | Docker Compose verification | **Closed 2026-11-19.** Stack built and verified. Two defects were fixed: env template names did not match the app, and the image re-synced dev dependencies at start-up |
| M2-2 | Browser E2E | **Closed.** 11 Playwright tests pass against the Compose stack. They use the installed Google Chrome, because the bundled Chromium is blocked by Windows policy. The run found a real defect: the verify page sent its single-use token twice under React StrictMode (fixed) |
| M2-3 | Admin invite to join an existing organization is not built | Users only get personal workspaces | M2.1, per ADR-015 |
| M2-4 | Rate limiting is in-process | Limits do not hold across multiple API instances | Shared store (Postgres or Redis) before scaling out |
| M2-5 | Email is written to an outbox table, not sent | Users need database access in development to get the verification link | SMTP adapter reads `email_outbox` (M2.1 or M10) |
| M2-6 | Python 3.12 used for the dev venv, target is 3.13 | Minor version gap | Re-test on 3.13 before M10 |
| M2-7 | Windows policy workarounds (ADR-022) | Local only | Revert when native modules are allowed |
| M2-8 | Audit verifier has no API endpoint | Integrity can be checked by code or by an operator only | Add an admin endpoint in M2.1 |
| M2-9 | No MFA; idle session timeout not implemented | Weaker session controls than the security architecture target | MFA before production (M10) |

## Milestone 3 known issues (2026-11-19)

| ID | Issue | Impact | Plan |
|---|---|---|---|
| M3-1 | Nothing past the first review gate can run until approvals exist | The M3 exit criterion "a deterministic workflow executes" is met only up to AWAITING_HUMAN_REVIEW | Milestone 4 |
| M3-2 | No job queue; stage runs happen inline in the request or script | Long-running work would block; no retries after a crash | DB-backed queue with leases (ADR-004), M5 or M6 |
| M3-3 | Workflow definitions are seeded from code, not published through an API | Administrators cannot add a template without a code change | Workflow Studio, M8 |
| M3-4 | Executions only report RUNNING; no completion, pause or cancel | No whole-workflow lifecycle yet | After M4 approvals |
| M3-5 | Stage run is exposed only in code (`run_deterministic_stage`), with no API route | Correct for security (users cannot drive stages), but nothing can run stages from the UI yet | Internal runner endpoint behind a worker, M5/M6 |
| M3-6 | Stage output is stored (`output_json`) but never shown | Intended for now; owner-visible artifacts come with M4 | M4 |

## Milestone 4 known issues (2026-11-19)

| ID | Issue | Impact | Plan |
|---|---|---|---|
| M4-1 | Conditional approval policies are refused | Cannot express "security approval only when risk is high" | Conditional policies with a restricted expression evaluator, M4.1 |
| M4-2 | Artifact content in Postgres JSONB, not object storage | Large documents and binary artifacts do not fit yet | Object storage (ADR-030), M5 or M10 |
| M4-3 | No mandatory sensors; validation snapshot lists none | Gates do not yet run deterministic checks | Sensor framework, M7 |
| M4-4 | Every artifact is visible to all project members | No owner-visible flag yet; internal drafts would be visible too | Owner-visible flag per artifact kind, M9 |
| M4-5 | No API to add or remove project members | Multi-approver policies are tested by inserting members in code | Membership management with org admin invites, M2.1 |
| M4-6 | Rework and upstream-change runs have no API route | Only code (and the Compose container) can run them; there is no worker yet | Worker with queue, M5/M6 |
| M4-7 | Nonce expiry for approval requests is not built | Replay is limited by idempotency keys, not by time-bound nonces | M4.1 with rate limiting on decisions |
| M4-8 | `REJECTED` has no reopen route | A rejected stage stays rejected until a future admin action | Reopen command with audit, M8 |
| M4-9 | Approval audit events carry the person's id, not a separate actor record | Adequate for now; evidence of exact screen shown is not recorded | Store the review snapshot, M9 |

## Milestone 5 known issues (2026-11-19)

| ID | Issue | Impact | Plan |
|---|---|---|---|
| M5-0 | **Live vendor calls are unverified.** No keys are configured; adapters are tested only against mocked HTTP | The first real call may fail on a detail the mocks do not reproduce | Add keys (owner decision), run `-m live` tests, fix any drift |
| M5-1 | AI calls run inside the stage transaction (ADR-034) | Network latency holds row locks on the stage | Worker with lease, with the queue |
| M5-2 | Base URL for OpenAI-compatible servers is user-supplied | Server-side request forgery risk: a user could point the platform at internal services | Allow-list or egress proxy before any multi-tenant use |
| M5-3 | No streaming and no tool calling | Owners see results only after a stage completes; agents cannot call tools yet | Streaming and tool grants in a later milestone (AGENT_ARCHITECTURE section 7) |
| M5-4 | Key rotation records the new key version but no re-encryption job exists; no KMS or data-key envelope | Keys stay under one configured key | KMS integration and rotation job, M10 |
| M5-5 | No token or spend budgets per organization | Retries and fallbacks can spend without a ceiling | Budget policy and enforcement, M10 |
| M5-6 | Health probes run on demand only | A broken provider is found when a stage fails | Scheduled probes, with the worker |
| M5-7 | Prices are not shipped; cost stays blank until entered | Cost reports are incomplete | Maintained price file with source and date |
| M5-8 | Context manifest per run is not stored (AGENT_ARCHITECTURE section 6) | Cannot yet list exactly which inputs an agent received | Store manifest IDs, M6 |
| M5-9 | Mock provider can be created only in development or test | Demos outside those environments need a real provider | Accepted |

## Live verification update (2026-11-19)

- M5-0 partly closed: the adapter path is verified live against a local Ollama model (`qwen3-vl:4b-instruct`, served through Ollama's OpenAI-compatible endpoint). Two live tests pass: a structured answer from the adapter, and a full stage run through the product with a health probe.
- Hosted vendors (Anthropic, OpenAI, Gemini) are still unverified: no keys.
- Local models are slow on CPU; the live test allows 300 seconds per call.

## Milestone 6 known issues (2026-11-19)

| ID | Issue | Impact | Plan |
|---|---|---|---|
| M6-1 | Skills are not built | Agents cannot share reusable instructions | Skill records with versions, M7 or later |
| M6-2 | Development sandbox (ADR-017) is not built | Design stages cannot generate runnable prototypes | Sandbox with no network, resource limits and an isolated preview origin, before design generation |
| M6-3 | Reviews are advisory | A reviewer can recommend changes and the gate still opens | Blocking reviews with sensors, M7 |
| M6-4 | No tool has an executor; only READ can be granted, and no READ tool runs yet | Agents cannot read the project through tools | Tool executors with per-run limits, M6 follow-up |
| M6-5 | Context manifests store ids and counts, not prompt hashes | Auditors cannot see the exact text a run received | Store prompt hashes per run, M10 |
| M6-6 | Agents are created through the API only | No visual editor for profiles and agents | Workflow Studio, M8 |
| M6-7 | A review can be answered by a fallback provider | The reviewer may not use the provider configured for its role | Pin reviewer provider in the agent version, M6 follow-up |
