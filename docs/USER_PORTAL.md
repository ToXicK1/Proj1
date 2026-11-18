# End-User Project Portal and Interaction Layer

Status: Design (Milestone 1 addendum). Implementation: Milestone 9 (M9), with groundwork in M2 (identity and roles), M3 (engine commands), M4 (approvals), M6 (agents).

## 1. Position in the platform

The portal is a **separate presentation and interaction layer** over the existing workflow engine, approval engine and agent orchestration. It does not create a second orchestrator and does not talk to providers directly.

```
Project Owner (browser)
  -> Portal UI
  -> Portal API  /api/v1/portal/*           (own response models; no internal fields)
  -> Intent classification & routing         (LLM allowed here; output is typed and validated)
  -> Authorization & policy checks           (project membership, owner permissions, stage state)
  -> Professional profile interface          (representatives: name, voice, allowed actions)
  -> Engine commands / approval service      (the same services the internal console uses)
  -> Agent orchestration -> provider abstraction -> artifacts -> sensors -> engine
```

Hard rules (from the brief, restated as invariants):

- The owner and the LLM never change workflow state directly. They submit *requests* that the engine evaluates.
- Every owner action is authorized against project membership and owner permissions in the backend.
- Owners never see provider names, keys, prompts, raw conversations with agents, tool calls, orchestration internals or chain-of-thought.
- Internal agent conversations are stored separately from owner messages and are never returned by portal endpoints.

## 2. Roles and boundaries

New first-class role: **Project Owner** (`project_owner`). Assigned per project; an organization can have many.

| Capability | Project Owner | Org Admin | Internal Reviewer | Platform Admin |
|---|---|---|---|---|
| Create project, upload files, converse | yes | yes | no (may view project) | yes (support) |
| View deliverables and previews | yes (owner-visible artifacts) | yes | yes | yes |
| View internal prompts, agent runs, traces | **no** | no | no | support access, audited |
| Approve owner-gated deliverables | yes (configured gates only) | no | no | no |
| Approve internal gates | no | policy-based | yes (slot) | no |
| Edit internal rules, hooks, sensors, agents | **no** (may propose feedback only) | yes | no | yes |
| Access provider keys | **no** | no (may manage, not view) | no | yes (audited) |
| Bypass mandatory validation | **no** | **no** | **no** | **no** (risk acceptance only through the governed path) |

Owner-visible artifact flag: artifact kinds and versions have `owner_visible` set by the workflow configuration. Internal drafts (e.g., raw agent notes) are never owner-visible.

## 3. Information architecture

### 3.1 Top-level (user-facing)

Home · My Projects · Create Project · Project Workspace · Deliverables · Reviews & Approvals · Notifications · Account Settings.

### 3.2 Inside a project

Overview · Project Team · Lifecycle · Conversations · Requirements · Architecture · Design · Development · Testing · Release · Documents · Activity & Decisions.

Sections are shown according to workflow state and permissions. For example, "Testing" appears in the navigation with an action only when QA opens a user-testing milestone; before that it shows status text such as "Not started yet".

## 4. Home and project creation

- After login, owners land on `Home`: "What would you like to build today?"
- Project type cards: Web Application, Mobile Application, SaaS Platform, AI Application / AI Agent, API / Backend System, Enterprise Software, Automation / Workflow System, Data Platform / Analytics, E-commerce Platform, Custom Project.
- Choosing a card is a starting hint, not a restriction. A free-text description is always available, and "something else" stores a custom type string.
- The conversation panel is persistent. Discovery is one question at a time, prioritized by missing information (name, problem, users, objectives, core features, platforms, design preferences, constraints, budget or timeline, references, uploads).
- "I don't know" and "you decide" are first-class answers. A decision the platform makes is recorded as an *inferred* item, not as a confirmed requirement.

## 5. Intake package and confirmation

Structured intake record fields carry a **status tag** per item:

| Tag | Meaning |
|---|---|
| Explicit | The owner stated it |
| Inferred | The platform concluded it; visible as an assumption |
| Uncertain | Conflicting or unclear; needs clarification |
| Needs clarification | Owner must answer before BA proceeds |
| BA recommendation | Added later by the Business Analyst profile; never shown as owner-stated |

Before formal requirements work starts, the owner sees a readable summary (understanding, problem, users, features, important assumptions, questions) and can correct or confirm. Corrections create a new intake revision; only a confirmed revision is routed to the Business Analyst profile as the formal starting point.

"Never silently convert assumptions into confirmed requirements" is enforced by the data model: `confirmed_requirements` can only be created from items tagged Explicit or from owner-confirmed Inferred items.

## 6. Project workspace

### 6.1 Overview

Project name and description, type, owner, current lifecycle stage, overall progress, current stage status, pending user actions, recent activity, important decisions, upcoming milestones.

### 6.2 Lifecycle tracker (six professional profiles)

Each profile card shows one of: Not Started, In Progress, Awaiting User Input, Awaiting Review, Changes Requested, Approved, Completed, Blocked.

- Mapping from engine state to display status is a fixed table in the backend (e.g., `AWAITING_HUMAN_REVIEW` with an owner gate -> "Awaiting Review"; `CHANGES_REQUESTED` -> "Changes Requested"; `BLOCKED` -> "Blocked"). The frontend does not compute it.
- **Progress percentage** is computed from stage execution data: `approved_or_skipped_stages / in_scope_stages`, weighted by stage weight defined in the workflow version. No LLM is used. The formula is documented and tested.
- Opening a profile shows: work in progress (non-internal summary), completed work, deliverables produced, decisions made, and what is waiting on the owner.
- Raw execution traces, prompts and orchestration details are never shown.

### 6.3 Deliverables

Central list of owner-visible artifacts (BRD, SRS, architecture diagrams, database design, API specs, UI wireframes and prototypes, source and build artifacts, test plans and reports, security reports, deployment docs). Each supports version history, preview (sanitized), comments and download, all subject to permissions. Source code download is a configured, owner-visible option, not a default.

## 7. Professional communication layer

Named representatives per profile (for example: Business Analyst, Solution Architect, UI/UX Designer, Software Developer, QA & Security Engineer, DevOps & Release Engineer). Each has a display name and a role title; the name is not tied to a real person. Representatives map to profiles, not to models.

Voice rules:

- Model names, provider names, agent names, tool names, workflow commands, internal orchestration decisions and chain-of-thought never appear in owner-facing text.
- Outbound messages are generated from templates with slots, or from model output that passes a **vocabulary filter** (a list of reserved internal terms, from the reference's voice contract: `stage`, `gate`, `sensor`, `hook`, `agent`, `scope`, `audit`, `engine`, and provider names) and is rewritten or rejected when it contains them.
- Examples from the brief are the target tone: "We have prepared the first version of your dashboard. Please review the navigation, layout, and visual style. You can request changes directly here."

## 8. Message routing

Every owner message is classified with these inputs: project ID, current lifecycle stage, candidate target profile, conversation context, message intent, related artifact/version, and owner permissions.

Intent enum: `ask_question`, `clarify_requirement`, `request_change`, `report_defect`, `provide_approval`, `reject_deliverable`, `request_explanation`, `submit_information`, `new_scope_request`, `feedback_general`.

Classifier output (validated, not trusted):

```json
{ "intent": "report_defect", "target_profile_key": "qa_security", "related_artifact_version_id": null, "confidence": 0.82 }
```

Backend validation (all must pass, else clarifying question or refusal):

1. intent is in enum; target profile is in the project's active workflow and reachable from the current stage;
2. artifact version (if any) belongs to this project and is owner-visible;
3. the owner's permission allows this intent on this stage (for example, `provide_approval` only on owner-gated stages);
4. the action maps to an allowed engine command.

Users cannot name internal agents or tools in messages. Text such as "run the security agent" or "call the deploy tool" is classified as a request; the router never maps free text to tool names. Tested with prompt-injection cases (`tests/security/`).

## 9. Feedback classification and change management

Owner feedback is classified into one of: Defect, New requirement, Enhancement, Usability feedback, Security concern, Question, Scope change. Routing:

| Classification | Routed to | Path |
|---|---|---|
| Defect | Software Developer via QA | QA triage -> defect record -> developer rework -> QA retest |
| New requirement / scope change | Business Analyst | Change management: impact on schedule, profiles and approved artifacts; may require new approval |
| Enhancement | Business Analyst or UI/UX (by topic) | Change request |
| Usability feedback | UI/UX Designer | Design change request on the relevant artifact version |
| Security concern | QA & Security | Security workflow, cannot be closed by owner |
| Question | Named representative | Answer; may create a clarification item |

Classification is recorded with reason and the classifier version. The QA representative can reclassify with a reason; reclassification is audited.

## 10. Change requests

Each change request has: request ID, originating owner message, target artifact and version, assigned profile, priority, status, resolution notes, resulting artifact version. Statuses: `open`, `triaged`, `in_progress`, `ready_for_review`, `resolved`, `rejected`, `withdrawn`.

Distinctions maintained in the data model and UI:

| Kind | Changes workflow state? |
|---|---|
| Feedback (comment) | No |
| Change request | May move a stage to `CHANGES_REQUESTED` |
| Formal approval | Satisfies an approval slot |
| Formal rejection | Moves the stage to `REJECTED` |
| New scope request | Opens change management; may require new approval of affected artifacts |

## 11. Design participation (UI/UX milestone)

1. Notification: "Design ready for your review".
2. Preview: the running prototype, generated as real front-end code and served from an isolated preview origin with no access to backend cookies or APIs (ADR-017).
3. Explanation: design decisions in plain language, written by the UI/UX representative from the design rationale (sanitized).
4. Feedback: owners write comments or change requests in plain language. Each is attached to the artifact version it was made on.
5. Processing: change request -> UI/UX revision run -> new version -> applicable design sensors (accessibility checks, consistency checks) -> presented again.
6. Comparison: side-by-side or toggle view of any two versions of a design artifact (screenshots or rendered diffs; version metadata shown).
7. Decision: approve this version or request further changes.
8. Downstream: an approved design version is the input to Development. If a later design change affects an approved downstream stage, the engine invalidates the affected approval and creates the rework path (`WORKFLOW_ENGINE.md` section 5). The owner sees which items were affected and why.

Example feedback mapping: "I don't like this color scheme" -> design change request tagged `visual.color`; "Move the navigation to the left" -> `layout.navigation`; "Add a dark mode" -> `feature.theme` (may be classified as new scope if not in the approved requirements; then change management applies).

## 12. QA participation (testing milestone)

1. Notification: "Testing ready for your participation".
2. Environment: a preview/test environment link, provisioned by DevOps stages for the test window, with test credentials issued to the owner via the platform (never shown in logs or prompts).
3. Functionality summary: what is ready to test, in plain language, with links to acceptance criteria.
4. Structured observation form: steps, expected result, actual result, severity hint, attachments (screenshots and recordings, scanned and stored as untrusted uploads).
5. Direct communication with the QA & Security representative.
6. Owner can: test, report a defect, describe unexpected behavior, suggest improvements, confirm expected behavior, request additional scenarios.
7. QA classifies and routes (section 9). Defects go to development through the QA workflow; fixes trigger QA retests; results are visible to the owner: executed test cases, pass/fail, open defects, resolved defects, outstanding risks, items awaiting owner confirmation.
8. **User approval never overrides failed mandatory security checks or deterministic test requirements.** The UI shows these as blockers with the reason; the API refuses the approval with `sensor_blocking`.

## 13. Notifications and pending actions

Notification types: project created; clarification required; requirements ready for review; architecture ready; design ready; design changes completed; development milestone completed; testing ready for participation; defects needing input; release approval required; deployment completed.

Rules:

- Pending actions are derived from workflow state by a backend projection (`pending_actions` recalculated on each relevant event), never edited by the UI.
- Each pending action states **what** is waiting, **why**, and **what the owner must do**, with one primary button.
- A workflow never waits silently: any owner-gated stage without action for a configurable interval produces a reminder notification.

## 14. Authorization and isolation

- Every portal endpoint checks: authenticated human, project membership with owner role (or other allowed role), project status, and resource ownership by project ID in the query.
- Conversations and messages are isolated by project and tenant; search and listing always scope by project.
- Owner responses use dedicated response models; internal fields (agent run IDs, prompts, provider IDs, tool names) are absent by schema and tested for absence.
- Uploads are untrusted and never executed; previews are sanitized; download links are short-lived signed URLs bound to the owner session.
- Idempotency keys on owner approvals; approvals are version-bound and audited (`APPROVAL_GOVERNANCE.md`).

## 15. Audit

All of these produce audit events with actor type `human` (owner), `system` (routing) or `ai_agent` (representative output): message received, classification stored, routing decision, change request created/updated, approval submitted/decided, notification sent, upload scanned, download granted, feedback reclassified. Internal agent message content is referenced by ID only.

## 16. Acceptance criteria mapping

| Brief criterion | Where addressed |
|---|---|
| 1. Lands on creation portal after auth | Section 4, M9 |
| 2. Select type or describe custom idea | Section 4 |
| 3. Conversational idea explanation | Section 4 |
| 4. Structured intake package | Section 5, data model `intake_records` |
| 5. BA receives package via routing | Data flow section 4 |
| 6. Review and correct understanding | Section 5 |
| 7. Real-time lifecycle progress | Sections 6.2 and `SYSTEM_DESIGN.md` section 5 (SSE) |
| 8. Communicate with relevant profile | Sections 7 and 8 |
| 9. Review and request changes to UI/UX | Section 11 |
| 10. Design feedback tied to artifact version | Sections 11 and 10 |
| 11. Participate in testing and report defects | Section 12 |
| 12. QA classifies and routes feedback | Section 9 |
| 13. Approve or reject deliverables | Section 8 of `APPROVAL_GOVERNANCE.md` and section 10 here |
| 14. Approvals tied to exact versions | `APPROVAL_GOVERNANCE.md` section 3 |
| 15. Invalidation on artifact change | `WORKFLOW_ENGINE.md` section 5 |
| 16. No access to LLM credentials, prompts, orchestration | Sections 1 and 14; security tests |
| 17. Cannot bypass mandatory validations | Section 12.8; `APPROVAL_GOVERNANCE.md` section 5 |
| 18. Auditable messages, feedback, changes, approvals | Section 15 |
| 19. Frontend never authority for state | Sections 1 and `SYSTEM_DESIGN.md` section 4 |
| 20. Multi-project, multi-user isolation | Section 14; `SECURITY_ARCHITECTURE.md` section 3 |

## 17. Integration plan with milestones

- **M2 (foundation):** users, organizations, projects, `project_owner` role, project membership, authorization base classes. Create project endpoint and minimal portal Home.
- **M3 (engine):** owner-visible flag on artifacts; progress projection; pending-action projection.
- **M4 (approvals):** version-bound approvals for owners and internal reviewers; change-request kinds and status machine.
- **M6 (agents):** representative templates; routing classifier as an internal agent with a narrow grant; intake agent.
- **M9 (complete lifecycle):** intake confirmation, design participation, QA participation, notifications, full owner UI.

## 18. Testing focus for the portal (added to `TEST_STRATEGY.md`)

- Owner cannot access internal fields: schema-level and response scan tests.
- Owner cannot approve non-owner gates, cannot approve when a mandatory sensor fails, cannot approve a superseded version.
- Owner cannot reach another project's conversations or artifacts by guessed IDs.
- Injection in owner messages does not produce tool calls or state changes.
- Assumption-to-requirement guard: inferred items cannot be routed as confirmed requirements.
- Vocabulary filter rejects reserved internal terms in owner-facing templates.
