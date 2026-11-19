# Collaboration Architecture (target)

The collaboration hub lets departments, their AI specialists and their human professionals discuss, challenge and hand off work. It is new.

## Channels

| Type | Purpose | Created when |
|---|---|---|
| PROJECT_TEAM_ROOM | Whole-team discussion | Project start |
| PROFILE_DIRECT_MESSAGE | Two departments | First message between them |
| STAGE_HANDOFF | Formal handoff of approved outputs | A department's package is approved |
| REVIEW_DISCUSSION | Discussion of one review package | Review package created |
| BLOCKER_ESCALATION | A blocker needing a decision | Blocker raised |
| DECISION_DISCUSSION | A decision under discussion | Decision proposed |

## Messages

Message ID, project, channel, thread, sender (AI department, human user, or system), recipient (department, user, or channel), type (question, answer, challenge, proposal, objection, handoff, decision, blocker, finding, event), content, artifact references with versions, stage, decision or change request, timestamp, visibility (internal, owner-visible), correlation ID. Mentions notify. History is searchable.

## How AI departments talk

Agents never call each other directly (AWS principle A8). The orchestrator routes:

1. A specialist's output may include structured `questions_for` or `objections` addressed to another department.
2. The orchestrator posts them as messages and enqueues a response job for the addressed department's representative agent, with only that department's context plus the referenced artifacts.
3. Answers are posted back. Unanswered required questions keep the asking stage in AWAITING_USER_INPUT or BLOCKED.

## Human participation

Professionals and owners can post in any channel they can see, ask for justification, challenge, correct, and direct AI work where their permissions allow. A human instruction to change work becomes a change request through the normal rework path; chat never moves state.

## Handoffs and decisions

A handoff record lists approved artifacts and versions passed downstream, open questions, and risks. A decision record holds the question, options, the chosen option, rationale, who decided, and links.

## Disagreements

The engine detects material disagreement (an objection on approved requirements, scope, security, architecture or production risk, or a reviewer and producer conflict on a blocking finding). It opens a BLOCKER_ESCALATION channel, pauses the affected stage, collects evidence, and asks the assigned human professional to decide. AI may propose a resolution; it cannot apply one.

## Visibility

AI messages, human messages and system events are visually distinct. Internal channels are hidden from owners unless marked owner-visible. Internal discussion never advances the workflow.
