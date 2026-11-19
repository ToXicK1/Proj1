# Workflow Engine (target)

Supersedes `docs/WORKFLOW_ENGINE.md` where they differ. The engine is the only authority over lifecycle state.

## States

NOT_STARTED, READY, RUNNING, AI_COMPLETED, VALIDATING, UNDER_REVIEW, AWAITING_USER_INPUT, AWAITING_APPROVAL, CHANGES_REQUESTED, REJECTED, APPROVED, COMPLETED, BLOCKED, FAILED, CANCELLED, SKIPPED.

Mapping from today: AWAITING_HUMAN_REVIEW is split into UNDER_REVIEW (AI reviewer running) and AWAITING_APPROVAL (waiting for a human). AWAITING_USER_INPUT is new (a clarification question to the owner). COMPLETED already exists for validated system steps.

## Transition rules

Transitions are a central table of (from, to, allowed actors, guard). Guards are deterministic checks:

- upstream dependencies satisfied (APPROVED, COMPLETED or SKIPPED);
- required input artifacts exist and are approved;
- mandatory sensors pass on the exact version;
- the required AI review exists for that version;
- the approval policy is satisfied by valid human decisions bound to that version and review package;
- no open blocking escalation or unanswered required user input.

AI agents and providers appear in no allow-list. A transition, its log row, its audit event and the next job are written in one transaction, under a row lock on the workflow execution.

## Stage kinds

| Kind | Example | Gate |
|---|---|---|
| system | workspace setup | none, validated only |
| ai_work | Requirements Analysis | AI review, then human professional approval |
| review_aggregate | BA Human Professional Review | professional approves the department package |
| owner_input | BA User Review | owner sends input or confirms none; the professional then decides and approves (RD-2) |
| user_input | clarification | waits for the owner's answer |
| execution | Unit and Integration Testing | real sandbox evidence required |
| release | Deployment and Verification | explicit release authorization plus evidence |

## Dependencies

Directed acyclic graph with sequential edges, parallel branches with an explicit join, and conditional edges. Conditions are deterministic expressions over project facts (project type, applicability scope, intake answers, upstream artifact fields), never model text. Applicability profiles (adapted from AWS scopes) skip stages before execution; mandatory governance stages cannot be skipped.

## Rework, escalation and recovery

- Request changes returns the stage to its rework path with feedback; rework is bounded.
- QA findings route to the owning department (defect to Developer, scope to BA, usability to Designer, architecture to Architect, security to all relevant).
- An approved upstream change invalidates dependent approvals by policy and reopens them with a recorded reason.
- Escalation pauses the stage until resolved by the assigned human.
- Every step runs as a job; a worker crash leaves the job to be retried, and steps check current state before acting.

## Versioning

Projects stay on the workflow version they started with. Migration to a newer version is an explicit, audited administrator action that maps stages and keeps history.
