# Hooks Analysis

Source: `core/hooks/` (20 TypeScript files), `harness/claude/settings.json`, `docs/reference/06-hooks-and-tools.md`.

## AWS hooks

They are assistant-harness hooks (PreToolUse, PostToolUse, UserPromptSubmit, SessionStart). They guard the assistant itself:

| Hook | Purpose |
|---|---|
| `aidlc-state-transition-guard` | Stops agents writing runtime state or routing commands |
| `aidlc-plan-approval-guard` | Code generation must have an approved plan first |
| `aidlc-review-freeze` | No writes between a review receipt and the gate |
| `aidlc-reviewer-scope` | Reviewers read only their scope |
| `aidlc-run-sensors` | Runs applicable sensors after each write |
| `aidlc-write-audit-log` | Records artifact creation and updates |
| `aidlc-record-human-turn` | Records that a real human spoke (human-presence evidence) |
| `aidlc-deliver-stage-rules` | Delivers required rules to sub-agents |
| Session, status line, install hooks | Harness housekeeping |

## Our model

Our platform hooks (built in Milestone 7) are lifecycle event subscriptions with declarative actions (require approval, run sensor, notify), priorities, conditions, timeouts, retries, and fail-closed or advisory policies. Most AWS guards are enforced structurally by our server: agents have no write path to state, reviewer context is a manifest, and sensors run on each new version.

## Changes for the rebuild

- Rename and extend events to the prompt's list (PROJECT_CREATED, INTAKE_COMPLETED, REVIEW_STARTED, APPROVAL_REVOKED, USER_FEEDBACK_RECEIVED, DEPLOYMENT_REQUESTED and others) with a mapping from existing names.
- Add actions: dispatch review, context refresh, escalate, create rework.
- Add a review-freeze rule: a version under review cannot be replaced except through the rework path.
- Keep "no arbitrary hook code". Any future code hook runs only in the sandbox after approval.

Decision: ADAPT (concepts), EXCLUDE (harness code).
