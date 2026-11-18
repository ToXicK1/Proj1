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
| M2-2 | No browser end-to-end test yet | The UI flow is verified by typecheck, unit tests and the HTTP smoke run, not in a browser | Add Playwright tests in M2.1 |
| M2-3 | Admin invite to join an existing organization is not built | Users only get personal workspaces | M2.1, per ADR-015 |
| M2-4 | Rate limiting is in-process | Limits do not hold across multiple API instances | Shared store (Postgres or Redis) before scaling out |
| M2-5 | Email is written to an outbox table, not sent | Users need database access in development to get the verification link | SMTP adapter reads `email_outbox` (M2.1 or M10) |
| M2-6 | Python 3.12 used for the dev venv, target is 3.13 | Minor version gap | Re-test on 3.13 before M10 |
| M2-7 | Windows policy workarounds (ADR-022) | Local only | Revert when native modules are allowed |
| M2-8 | Audit verifier has no API endpoint | Integrity can be checked by code or by an operator only | Add an admin endpoint in M2.1 |
| M2-9 | No MFA; idle session timeout not implemented | Weaker session controls than the security architecture target | MFA before production (M10) |
