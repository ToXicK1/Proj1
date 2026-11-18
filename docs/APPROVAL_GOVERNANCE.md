# Approval Governance

Status: Proposed (Milestone 1). Implementation: Milestone 4 (internal approvals) and Milestone 9 (owner approvals via portal).

## 1. What an approval is

An approval is a **human authorization decision** bound to one exact artifact version. It is not a boolean on a stage, not an agent output, and not a chat message. It is a row in `approval_decisions` with these required fields (matching the brief):

| Field | Source | Notes |
|---|---|---|
| `id` | server | UUID |
| `organization_id`, `project_id` | server, from the stage | tenant and project binding |
| `profile_id`, `stage_execution_id` | server | which professional stage |
| `artifact_id`, `artifact_version_id` | request, validated by server | must belong to the stage and be the current gate version |
| `artifact_content_sha256` | server, read from version | the bytes the human judged |
| `approver_principal_id` | authenticated session | must be `principal_type = human` |
| `approver_role_at_decision` | server snapshot | role used to satisfy the policy |
| `decision` | request | `APPROVE`, `REJECT`, `REQUEST_CHANGES` |
| `comment` | request | optional for approve, required for reject and request changes |
| `validation_snapshot` | server | JSON of sensor and review results as shown to the human, with their IDs and statuses |
| `finding_dispositions` | request | how each open finding was treated (accepted risk, fix requested) |
| `policy_slot` | server | which policy slot the decision satisfies |
| `status` | server | `ACTIVE`, `SUPERSEDED`, `REVOKED` |
| `decided_at` | server clock | UTC |
| `idempotency_key` | request header | unique per approver and stage |

The database enforces `principal_type = 'human'` for this table (CHECK constraint on the joined principal, plus a service-layer assertion). AI agents and provider accounts cannot hold approval rights, so they cannot produce these rows even with a bug in the service layer.

## 2. Approval policies

Policies are configured per gate in a profile or stage version. Supported types:

| Type | Meaning |
|---|---|
| `single` | One named approver slot, satisfied by one human |
| `any_of` | Any one authorized approver from a set satisfies |
| `all_of` | Every listed approver must approve |
| `role_based` | Any human holding a listed project role satisfies a slot |
| `sequential` | Slots fill in order; a later slot opens only after the earlier one is satisfied |
| `conditional` | Slot applicability depends on a restricted expression over the snapshot (e.g. "security approval required when risk = high") |

Policies compile into a list of slots. The engine evaluates slots against the current artifact version only.

Mandatory gates: a stage marked `protected: true` cannot be configured without an approval policy (compiler check). Protected gates are the six profile completions and any gate the organization marks protected.

## 3. Approval lifecycle

```
AWAITING_HUMAN_REVIEW (version V)
   |-- approve (slots satisfied) --> APPROVED
   |-- reject ------------------> REJECTED
   |-- request changes ---------> CHANGES_REQUESTED  (feedback recorded; AI revision creates V+1)
   |
   | new version V+1 created (AI revision or human edit)
   v
approvals for V -> SUPERSEDED; stage -> VALIDATING -> AWAITING_HUMAN_REVIEW (V+1)
```

Important rules:

1. **Version binding.** An approval for V never satisfies V+1. Tested.
2. **Atomicity.** The approval row, the stage transition, the audit event and the downstream invalidation commit in one transaction (`WORKFLOW_ENGINE.md` section 3).
3. **Idempotency.** Repeating the same request with the same key returns the original decision, not a second approval.
4. **Concurrency.** Two approvers acting at once on a slot: the unique constraint on (stage_execution_id, artifact_version_id, policy_slot, approver) admits both; the stage transition re-evaluates the policy inside the lock. Tested with parallel requests.
5. **Replay.** A decision request carries a nonce bound to the session and an expiry; a captured request cannot be replayed after expiry or from another session.
6. **Authority checks happen server-side**, not by hiding buttons: approver must hold the project role required by the policy slot, must not be the principal who generated the artifact, and must not be an AI principal.

## 4. Separation of duties

- An approver cannot approve a stage they authored or edited (artifact `last_edited_by` check). Exception only where policy explicitly allows, and the exception is recorded.
- An independent reviewer (agent) cannot be the approver. Reviews are inputs, not approvals.
- The same human cannot satisfy two slots of one `all_of` policy.

## 5. Risk acceptance

A mandatory sensor failure can be overridden only by a `risk_acceptance` record:

- named human with a permitted role (`org_admin` or `security_approver`);
- reason (min length, required);
- specific sensor ID and version;
- expiry date (max configurable, default 30 days);
- bound to the artifact version (a new version voids it);
- audit event `stage.risk_accepted`.

Security-category sensors (SAST, secret detection, critical dependency vulnerabilities) cannot be accepted by a project owner, and no user approval overrides them. This is the "never allow user approval to override failed mandatory security checks" rule from the brief.

## 6. Owner (end-user) approvals

Project Owners approve only gates configured for owner participation (typically design and acceptance testing). Owner approvals:

- use the same approval table and rules as internal approvals;
- show the owner the artifact version, its change history and open items in plain language;
- cannot satisfy a gate that is not configured for owner participation;
- cannot override mandatory sensors or security gates (section 5);
- are recorded with the same audit fields.

## 7. Rejections and feedback

Feedback is not approval. The portal distinguishes:

| Kind | Effect on workflow |
|---|---|
| Feedback (comment) | Stored; no state change |
| Change request | Creates a `change_request` linked to artifact version, target profile, priority; may move stage to `CHANGES_REQUESTED` |
| Formal approval | Satisfies a policy slot |
| Formal rejection | Moves stage to `REJECTED` |
| New scope request | Routed to change management; may create a scope change requiring its own approval |

Full treatment in `USER_PORTAL.md`.

## 8. Audit

Every approval-related event is in the hash-chained audit: request received, authorization decision (allow or deny with reason), decision stored, slots satisfied, stage transition, supersession, risk acceptance, revocation. Denied attempts are logged too (for security testing and monitoring).

## 9. Test obligations (must exist before M4 exit)

- Unauthorized approver rejected (wrong role, wrong project, wrong tenant, AI principal).
- Approval for V does not satisfy V+1.
- Duplicate idempotency key returns original decision.
- Parallel approvals from two slots produce exactly one transition.
- Expired or replayed decision request rejected.
- Mandatory sensor failure blocks approval even with owner approval.
- Approval and transition are atomic: injected failure after approval insert rolls back both.
