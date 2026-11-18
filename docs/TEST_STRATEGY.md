# Test Strategy

Status: Proposed (Milestone 1).

## 1. Principles

- A feature is complete only when backend behavior, persistence, authorization, validation and relevant tests all work. An interface alone is not completion.
- Mock data never counts as proof of an integration. Provider integrations are tested with (a) a deterministic mock adapter for CI and (b) opt-in live tests against real providers, gated by secrets and marked `live`.
- Failing tests are never skipped silently. A skip requires a linked entry in `KNOWN_ISSUES.md` and an expiry.
- Every critical state transition has an automated test.

## 2. Layers

| Layer | Tooling | Scope | Runs |
|---|---|---|---|
| Unit (backend) | pytest | State machine, workflow compiler, permission engine, approval engine, rule resolver, hook dispatcher, sensor execution, provider adapters (mocked HTTP) | Every commit |
| Unit (frontend) | Vitest + Testing Library | Components, status mapping, form validation | Every commit |
| Integration (backend) | pytest + PostgreSQL in Docker Compose | Transactions, migrations, locking, artifact store (MinIO), workflow execution with mock provider, hook execution, agent handoffs, approval transitions | Every PR |
| Contract | OpenAPI diff + schema tests | Breaking API changes, response model field absence for owners | Every PR |
| End-to-end | Playwright | Full project path (section 4), portal flows, approval UI | Nightly and before milestone exit |
| Security | pytest security suite + OWASP ZAP baseline (later) + Semgrep + Bandit + gitleaks + pip-audit + npm audit | Section 5 | Every PR (fast subset) and nightly (full) |
| Live provider | pytest `-m live` | Real Claude/OpenAI/Gemini calls on a small fixed prompt set | Manual, budget-capped |
| Performance | Locust or k6 (M10) | Approval and transition throughput; concurrent approvals | M10 |

## 3. Mandatory unit and integration coverage

Unit:

- State machine: every legal edge succeeds with its guard; every illegal edge raises `InvalidTransition`; actor restrictions (AI actor cannot approve) enforced. Generated from the transition table so the table and the code cannot drift (test fails if a table row has no test).
- Workflow compiler: each check in `WORKFLOW_ENGINE.md` section 4 has a failing fixture and a passing fixture.
- Permission engine: role x action matrix from `SECURITY_ARCHITECTURE.md` section 3, checked exhaustively.
- Approval engine: policy types (single, any_of, all_of, role_based, sequential, conditional), version binding, supersession.
- Rule resolver: inheritance order org -> team -> project -> profile -> stage -> agent; additive semantics; conflict detection.
- Hook dispatcher: priority ordering, condition evaluation, timeout, fail_closed vs advisory behavior.
- Sensor execution: each status (`PASS`, `FAIL`, `WARNING`, `NOT_APPLICABLE`, `ERROR`); ERROR never treated as pass.
- Provider adapters: normalized error mapping, retry only on retryable errors, schema validation with one repair attempt, fallback preserves schema.

Integration:

- Migrations apply and roll back cleanly on empty and seeded databases.
- Concurrent transitions: two requests on the same stage, one wins, the other gets 409 (both lock order and version-check paths).
- Concurrent approvals: two approvers on a `all_of` policy produce exactly one transition at the correct time.
- Atomicity: injected exception after the approval insert rolls back the approval, transition and audit row together.
- Audit chain: write N events, verify chain; tamper a row, verification fails at the right index.
- Artifact versions: new content produces a new row; updating an existing version is rejected by DB trigger.
- Workflow execution with mock provider: all six profiles execute end to end with deterministic outputs.
- Event-to-emitter drift: every event type in the enum is emitted by at least one code path, and every emitting path uses a known event type.

## 4. End-to-end acceptance scenario (from the brief, Part 20)

Automated in Playwright plus API tests. Steps:

1. Create organization. 2. Create project. 3. Assign Business Analyst profile. 4. Submit requirements. 5. Run BA agent (mock provider in CI; live provider in the nightly live run). 6. Generate documentation. 7. Validate deliverables. 8. Attempt to advance without approval: **must be refused** with `invalid_transition` or `approval_required`. 9. Approve as an authorized BA. 10. Solution Architect stage becomes READY. 11. Generate architecture. 12. Independent architecture review. 13. Request changes. 14. Revised architecture (V+1). 15. Previous approval for V is SUPERSEDED (and attempting to use it fails). 16. Approve the new version. 17. Continue through the lifecycle. 18. QA and security gates verified (a failing mandatory security sensor blocks approval, including an owner approval). 19. Release authorization verified (EXTERNAL_SIDE_EFFECT requires explicit authorization).

The scenario is written as a single parametrized test module so that it stays runnable as the product grows.

## 5. Security test catalogue (from the brief, Part 20)

| Threat | Test approach |
|---|---|
| Unauthorized approvals | Each role x approval-slot combination; wrong project; wrong tenant; AI principal; owner on internal gate |
| Cross-tenant access | Fixtures with two organizations; every list and detail endpoint called with the other tenant's IDs; expects 404 |
| Privilege escalation | Owner calls admin endpoints; agent principal calls approval endpoints; role changes by non-admins |
| Invalid transitions | Every illegal edge through the API; attempts to submit `status` in bodies |
| Artifact tampering | Modify stored object after approval; hash check on approval and before delivery fails; DB update attempts blocked |
| Prompt injection | Corpus in `tests/security/prompt_injection/` against classifier, lead agent and reviewer with mock provider; asserts no state change, no tool invocation outside grant, no approval |
| Malicious tool inputs | Path traversal in file tools, oversized inputs, schema-violating inputs, shell metacharacters in tool arguments |
| Secret exposure | Seeded canary secrets; scan of all API responses, logs, audit payloads and error messages; any match fails |
| Hook abuse | Hook with unauthorized action; hook timeout; hook trying to write state; AI-generated hook activation without approval |
| Concurrent approval requests | Parallel submissions with same and different idempotency keys |
| Replay attacks | Reused approval nonce; expired nonce; approval payload replayed from another session |
| Owner information leakage | Owner-scoped responses checked against a forbidden-field list (prompts, provider names, agent run IDs, tool names) |
| CSRF | State-changing requests without token rejected |
| Rate limits | Login and AI-invoking endpoints return 429 after threshold |

## 6. Frontend tests

- Status mapping: each engine state maps to the display status in `USER_PORTAL.md` section 6.2.
- Approval form: confirmation dialog required for high-impact approvals; version shown; disabled when backend says not permitted (the backend remains authoritative; a test confirms the UI still handles a refusal).
- Accessibility: axe checks on key pages; keyboard navigation for approval and studio flows.
- Responsive layout: Playwright viewport tests at mobile, tablet and desktop widths.

## 7. Evidence and reporting

- Each milestone exit records: test counts by layer, failing tests (must be zero or listed in `KNOWN_ISSUES.md`), security test results, coverage of state transitions (100% of table rows), and the exit-criteria checklist in `IMPLEMENTATION_STATUS.md`.
- Coverage target: 85% line coverage on `workflows`, `approvals`, `audit`, `auth`; no numeric target elsewhere, to avoid gaming.

## Live tests against a local model (added 2026-11-19)

`backend/tests/test_live_ollama.py` runs with `pytest -m live` when these are set:
- `AIDLC_LIVE_OLLAMA_URL` (for example `http://127.0.0.1:11434/v1`)
- `AIDLC_LIVE_OLLAMA_MODEL` (for example `qwen3-vl:4b-instruct`)

They call a real local model through the OpenAI-compatible adapter, run a stage through the product path, and run the health probe. Without the variables they skip. Hosted-vendor live tests (Anthropic, OpenAI, Gemini) are not written yet because no keys are configured.
