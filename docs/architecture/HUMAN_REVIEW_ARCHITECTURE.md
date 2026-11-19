# Human Review Architecture (target)

## Assignments

- Organization-level qualification: a person holds one or more professional profiles, confirmed by an administrator (exists).
- Project-level assignment: per project and profile, one primary and any number of backup reviewers, with history. Default: organization holders, until a project assignment is set.
- Workload view: open review packages per reviewer.
- Reassignment and escalation are audited actions by a person with the permission.

## Review sequence

1. Specialist completes work; an immutable artifact version is stored.
2. The independent AI reviewer evaluates that exact version.
3. Sensors run.
4. A **review package** is frozen: artifact version, sensor results with evidence, AI findings, relevant requirements, context summary, previous feedback.
5. The assigned primary reviewer (or backups) is notified.
6. The professional inspects the package and acts.
7. The backend validates permission, version and package, then records the decision.
8. The engine commits the transition in the same transaction.

## Actions

| Action | Effect |
|---|---|
| APPROVE | Fills a policy slot for this package; transition when the policy is satisfied and checks pass |
| REQUEST_CHANGES | Feedback to the producing specialist; rework with a new version and a new package |
| REJECT | Stops the stage; restart needs an authorized action |
| ESCALATE | Opens a blocker escalation; stage paused |
| ADD_FINDING | Adds a human finding to the package; can be blocking |
| COMMENT | Non-binding note on the package |
| EDIT_ARTIFACT | Authorized reviewer creates a new human-authored version; the reviewer who edited cannot approve that version; sensors and AI review rerun |
| REASSIGN_REVIEW | Moves the review to another qualified person, with reason |

## Integrity

Each decision binds reviewer, organization, project, profile, stage, artifact, exact version, review package, decision, comment, timestamp and evidence snapshot. A changed version voids approvals of earlier packages; downstream approvals are invalidated by dependency and policy. Idempotency keys stop replays.

## Non-negotiable rules

AI never approves and its consensus never replaces a human. A missing reviewer makes the workflow wait and notifies administrators. No self-approval. Unauthorized reviewers are refused by the backend. Failed mandatory security and validation checks cannot be approved past (risk acceptance only where the stage allows it, never for security). Every action is audited.

## Owner input (decision RD-2)

The project owner never approves. Owners can read the department's work and send input, attached to the exact version, to the assigned professional. The professional reviews that input and decides whether to turn it into a change request for the AI. The prompt's "User Review and Approval" stages become owner input steps: the stage waits for the owner's input or a "no further input" confirmation, then the professional gives final approval. Only a department's assigned professional can approve its work.
