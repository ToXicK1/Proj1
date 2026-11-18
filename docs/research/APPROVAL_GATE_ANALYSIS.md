# Approval Gate Analysis

Status: Research, Milestone 1
Source: `core/knowledge/aidlc-shared/audit-format.md` (`STAGE_AWAITING_APPROVAL`, `GATE_APPROVED`, `DECISION_RECORDED`, `REVIEW_COMPLETED`), `core/hooks/aidlc-plan-approval-guard.ts`, `core/hooks/aidlc-review-freeze.ts`

## 1. How the reference gates a stage

1. Stage body writes artifacts.
2. Optional reviewer runs; its verdict is recorded with `Artifact Fingerprint` and `Request Id`.
3. Sensors run on the artifacts, results recorded as `Sensor State` on the gate row.
4. `STAGE_AWAITING_APPROVAL` opens the gate `[?]`, with a brief digest and a gate question record.
5. The person answers. The engine records `DECISION_RECORDED` -> `HUMAN_TURN` -> `QUESTION_ANSWERED`, then `GATE_APPROVED` with the person's words, the brief digest and the review finding dispositions.
6. Only the exact preceding sequence authorizes the approval (`Its authorization is the preceding exact DECISION_RECORDED -> HUMAN_TURN -> QUESTION_ANSWERED pair`).

Notable mechanisms:

- **Brief digest binding.** The approval records `sha256` of the review brief the person decided on. Changed brief means a new decision is needed.
- **Review finding dispositions.** Every open finding is mapped to `Accepted risk`, `Approved autonomously`, `Changed after review`, or `Fix requested`. Approval does not silently close findings.
- **Blocking-sensor override** requires a named reason and is audited.
- **Plan approval** is a separate gate before code generation, enforced by a PreToolUse hook (`aidlc-plan-approval-guard.ts`). The guard refuses project-code writes until the approval evidence is current.
- **Review freeze.** After a terminal review, writing a produced artifact voids the receipt, so the reviewed bytes are the approved bytes.

## 2. What the reference does well

- Approval authority is a **chain of recorded events**, not a boolean. The engine checks the chain.
- Approval references the exact content it judged (fingerprint and digest).
- Findings have explicit dispositions at approval time, so risk acceptance is visible.
- Overrides are explicit, reasoned and auditable.

## 3. Where it is weaker for our requirements

| Requirement (master prompt Part 7) | Reference behavior | Our design |
|---|---|---|
| Approvals only by humans, enforced by backend | Human turn recorded by a hook; the same developer's assistant can record human-looking evidence in a single-user setup | Approval is an API action by an authenticated human principal; the DB rejects approval rows with non-human actor type (CHECK constraint + service check) |
| Multiple approvers, all-required, any-one, role-based, sequential, conditional | Single approver per gate | `ApprovalPolicy` with policy types: single, any-of, all-of, role-based, sequential, conditional |
| Approval invalidated when artifact changes | Review freeze voids the review receipt; approval recorded against brief digest | `Approval` row binds `artifact_version_id` and `content_sha256`; a new version does not inherit approvals |
| Atomic approval and transition | Audit-first, state after; crash windows exist | Single DB transaction with `SELECT ... FOR UPDATE` on the stage row plus optimistic `version` column; approval row, stage transition and audit event commit together |
| Concurrent approvals | Single-user, not a concern | Unique constraint on (stage_execution_id, artifact_version_id, approver_id, policy_slot); idempotency key on requests |
| Project Owner (end user) approvals | None | Owner approvals are allowed only for gates configured for user participation, bound to the same version rules, and never override mandatory sensors or security gates |

## 4. Our approval state rules (summary)

- A protected gate opens only when: deliverable artifact version exists, required mandatory sensors are `PASS` (or an authorized exception exists), and the reviewer (if configured) is a different agent configuration with a verdict bound to the same version.
- A gate closes only by an approval or rejection event from an authorized human principal, inside a transaction that re-reads the artifact version and checks the content hash.
- Any new artifact version for the same logical deliverable sets its earlier approvals to `SUPERSEDED` and returns the stage to `CHANGES_REQUESTED` or `AWAITING_HUMAN_REVIEW` depending on configuration.
- Downstream impact: a change to an approved upstream artifact invalidates approvals of stages that consumed it (dependency edges recorded from `consumes[]`), and creates rework tasks.

The detailed design is in `docs/APPROVAL_GOVERNANCE.md`.
