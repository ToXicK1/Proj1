# State and Audit Analysis

Status: Research, Milestone 1
Source: `docs/reference/12-state-machine.md`, `core/knowledge/aidlc-shared/audit-format.md`, `core/knowledge/aidlc-shared/state-template.md`, `core/hooks/aidlc-write-audit-log.ts`

## 1. State model in the reference

Three nested machines plus one session stream:

- **Workflow**: `Running`, `Completed`, `Archived` (with unarchive). Events: `WORKFLOW_STARTED`, `WORKFLOW_COMPLETED`, `WORKFLOW_ARCHIVED`, `WORKFLOW_UNARCHIVED`.
- **Phase**: `Active`, verified, or skipped because scope excluded it.
- **Stage**: `[ ]` pending, `[?]` gate open, `[x]` complete, plus revise and reject.
- **Session**: events emitted by host hooks.

State is stored in `aidlc-state.md`, a Markdown file with fields such as `State Version: 8`, `Active Agent`, `Scope`, `Guard Policy`, `Stages to Execute`. The engine writes it; humans may read it.

Good: a single writer per field, a schema version, and a template document that defines the contract (`state-template.md`).
Weak for us: Markdown state is not concurrency-safe across users, cannot be queried efficiently, and has no row-level authorization.

## 2. Audit model in the reference

- Audit is a directory of **per-clone shards** under `<record>/audit/`.
- Each event type has a defined field set (`audit-format.md` tables: event name, meaning, required fields, emitting tool).
- **Audit-first atomicity:** the tool writes the audit row before mutating state. If audit emission fails, the tool throws.
- Important explicit caveat: audit shards are "operational evidence, not a tamper-proof" record. There is no cryptographic chaining in the format.

Taxonomy highlights (examples from the reference):

| Event | Meaning |
|---|---|
| `WORKFLOW_STARTED` | Scope determined, workflow begins |
| `STAGE_AWAITING_APPROVAL` | Gate opened, includes sensor state and open decisions |
| `REVIEW_REQUESTED` / `REVIEW_COMPLETED` | Reviewer dispatch and verdict with fingerprints |
| `DECISION_RECORDED` / `HUMAN_TURN` / `QUESTION_ANSWERED` | Human decision chain |
| `GATE_APPROVED` | Approval with person's words and disposition of findings |
| `SUBAGENT_DISPATCHED` / `SUBAGENT_COMPLETED` | Agent activity |
| `INTENT_REPOS_CHANGED` | Scope change record |

`docs/reference/12-state-machine.md` says a drift test (`t48-audit-event-emitters.test.ts`) keeps the tables in sync with the code. This is a good practice we will copy: **an emitter test that fails when an event is defined but never emitted, or emitted but undocumented.**

## 3. What we will do differently

| Concern | Reference | Our platform |
|---|---|---|
| Storage | Markdown + shard files | PostgreSQL tables, normalized, with FKs and indexes |
| Tamper evidence | None (explicitly not claimed) | `audit_events` is append-only (no UPDATE/DELETE grants; trigger blocks), each row stores `prev_hash` and `hash` (SHA-256 over canonical JSON including `prev_hash`). A periodic checkpoint signs the head hash. Verification endpoint recomputes the chain. |
| Concurrency | Single developer | Optimistic `version` on workflow and stage rows, `SELECT FOR UPDATE` in transitions |
| Tenancy | Not applicable | `organization_id` and `project_id` on every audit row; queries always scoped |
| Actor model | `Human`, `Agent`, `Hook`, `Tool` implied | Explicit `actor_type` enum: `human`, `ai_agent`, `system`, `hook`, `provider`, with `actor_id` FK where applicable; CHECK constraint prevents `ai_agent` from producing approval events |
| Secrets | Not stored | Never stored in audit metadata; a redaction layer runs before write; provider keys never reach audit |
| Correlation | Implicit by intent | `correlation_id` (request id / workflow run id) on every event |
| Retention | Not defined | Per-organization retention policy; audit rows for approvals and permission changes are not purgeable before the policy minimum; data deletion requests anonymize actor PII but keep chain integrity (hash of redacted payload) |
| Observability of AI usage | Usage folded via hook (`aidlc-fold-usage.ts`) | `AgentRun` and `TokenUsage` tables with provider, model, tokens, cost estimate, latency, success, retry count |

## 4. Design implications

1. Every state transition is a single transaction that writes the new state row and one or more audit events. There is no code path that changes state without an event.
2. The audit table is separate from application data and has its own write role. Application code appends; only a verification job reads the chain.
3. Hash chaining is per organization, so a tenant can verify its own history without seeing another tenant's rows.
4. Audit and state drift tests: a test enumerates all transition functions and asserts each emits the documented event (adopting the reference's t48 idea).
