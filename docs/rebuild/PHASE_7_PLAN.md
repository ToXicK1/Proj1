# Phase 7 plan: the six departments

Date: 2026-11-20. Exit check (REBUILD_PLAN.md): the Business Analyst department works end to end, on a real model,
before the other five are built.

## 1. Why this phase matters

Decision RD-1 (accepted 2026-11-19) made the default lifecycle the rebuild prompt's **department stage lists**:
BA 8, Architect 10, Designer 10, Developer 9, QA 11, DevOps 9 (57 stages). The platform still runs the AWS-style
33-stage lifecycle. Phase 7 builds the department lifecycle and makes it the default for new projects. The AWS
lifecycle stays importable, and running projects keep the version they started with.

## 2. Target stages (from the rebuild prompt)

| Department | Stages, in order |
|---|---|
| Business Analyst | Intake Review, Discovery, Requirements Analysis, User Story Development, Scope Definition, Requirements Review, Human Professional Review, User Review and Approval |
| Solution Architect | Requirements Analysis, System Decomposition, Technology Selection, Data Architecture, API and Integration, Security and Infrastructure, Architecture Documentation, Independent Review, Human Review, User Review |
| UI/UX Designer | Design Discovery, Information Architecture, User Journey Mapping, Wireframes, Visual Design, Prototype and UI Specs, Independent Review, Human Review, User Design Review, Design Approval |
| Software Developer | Repository and Environment Analysis, Development Planning, Environment Setup, Implementation, Unit and Integration Testing, Independent Code Review, Developer Rework, Human Review, Development Handoff |
| QA and Security | Test Strategy, Test Case Generation, Functional/Integration/Regression, Performance, Security Assessment, Defect Management, Independent QA Review, Human Review, UAT, Final Signoff |
| DevOps and Release | Deployment Planning, Environment Setup, Infrastructure and Containerization, CI/CD, Deployment Preparation, Release Readiness Review, Human Release Approval, Deployment and Verification, Operational Handover |

## 3. New stage kinds the engine needs

Today every AI stage is one "do the work, then a professional approves it" step. The department lists add three
kinds of step:

| Kind | Example | Behaviour |
|---|---|---|
| `ai_work` (exists) | Requirements Analysis | AI lead, independent AI review, sensors, then the gate (see decision Q1) |
| `ai_review` (new) | Requirements Review, Independent Code Review | An independent reviewer checks the department's work as a whole: consistency and traceability (requirements to stories to scope), with findings and severity. Advisory; blocking findings send the named stage back for rework. It never approves |
| `review_aggregate` (new) | Human Professional Review | The professional sees the department's whole package (every deliverable plus the review report) and approves it, or sends one named stage back with feedback |
| `owner_input` (new, RD-2) | User Review and Approval | The owner reads the package and either sends input or confirms "no further input". Input goes to the professional, who turns it into changes or not; the professional gives the final approval. The owner never approves |
| `execution` (exists via sandbox) | Unit and Integration Testing | Real sandbox evidence required |
| `release` (later) | Human Release Approval, Deployment and Verification | Explicit release authorization plus evidence. No real deployment target yet (RB-8), so plans only |

These reuse what Phases 5 and 6 built: the AWAITING_USER_INPUT state for the owner step, escalations, rework loops,
tools, specialists and per-stage jobs.

## 4. Business Analyst first (the exit check)

| # | Stage | Kind | Produces (outline) | Reads |
|---|---|---|---|---|
| 1 | Intake Review | ai_work | brief summary, gaps, assumptions, questions for the owner | confirmed brief |
| 2 | Discovery | ai_work | stakeholders, current process, market context, constraints | 1 |
| 3 | Requirements Analysis | ai_work | functional and non-functional requirements, business rules, assumptions | 1, 2 |
| 4 | User Story Development | ai_work | personas, user stories, acceptance criteria | 3 |
| 5 | Scope Definition | ai_work | in scope, out of scope, first release, success measures | 3, 4 |
| 6 | Requirements Review | ai_review | findings with severity, traceability gaps, verdict | 1 to 5 |
| 7 | Human Professional Review | review_aggregate | the professional's decision on the package | 1 to 6 |
| 8 | User Review and Approval | owner_input | the owner's input or "no further input", then the professional's final approval | 1 to 7 |

Work in order:
1. Engine and compiler: the `ai_review`, `review_aggregate` and `owner_input` kinds, plus department packages (which
   deliverables belong to the review). Tests for every new transition and guard.
2. The BA stages as a new department lifecycle template, with outputs, briefs and `reads`.
3. Workspace UI: the package review screen for the professional, and the owner's input step.
4. Tests, then a live run of the BA department on the local model, using the Phase 6 live spec pattern.

Exit: a project goes through all 8 BA stages on the real model, with the professional approving the package and the
owner giving input through the UI.

## 5. The other five departments (after the BA exit check)

- **Solution Architect and UI/UX Designer** both depend only on the BA package, so they can run in parallel (decision Q2).
- **Software Developer**: Implementation is today's code generation with real sandbox builds; Unit and Integration
  Testing needs real sandbox evidence; Developer Rework is the bounded rework loop driven by Independent Code Review.
- **QA and Security**: Defect Management loops defects back to the Developer with evidence (A9); UAT is an owner input step.
- **DevOps and Release**: the release stages produce plans and runbooks only until a real deployment target exists (RB-8).
- **Designer visual work** (Visual Design, Prototype) needs rendered previews to be honest. The first version renders
  HTML prototypes in the sandbox; anything less is labelled as text design.
- **Scopes:** project types and scopes choose which stages apply (as AWS scopes do today). Governance stages (reviews,
  owner input, human approval) can never be removed.

## 6. Decisions needed before building

| ID | Question | Options |
|---|---|---|
| Q1 | Approvals inside a department | (a) As documented in HUMAN_REVIEW_ARCHITECTURE.md: every AI stage is approved by the professional, **and** the department package is approved at Human Professional Review (BA: 5 + 1 approvals, about 45 per full project). (b) The professional approves only the package: AI stages inside a department chain on reviewed drafts, nothing leaves the department or reaches the owner until the professional approves the whole package (BA: 1 approval, about 8 per full project). |
| Q2 | Architect and Designer in parallel | (a) Yes, both start once the BA package is approved. (b) Keep everything sequential. |
| Q3 | Switch the default lifecycle | (a) New projects use the department lifecycle as soon as the BA department is ready, with the later departments filled in as they are built. (b) Keep the current lifecycle as the default until all six departments are done. |

### Answers (2026-11-20)

- **Q1: (a).** The professional approves every AI step and also the department package at Human Professional Review.
- **Q2: (a).** The Solution Architect and UI/UX Designer run in parallel once the BA package is approved.
- **Q3: (b).** Today's lifecycle stays the default until all six departments are built and tested; the BA department is tested on its own first.

## 7. Risks

- **Model size and context:** the local 4B model has a 4,096-token window (RB-20). More, smaller stages help, but the
  package review and the owner step send whole packages, so they will rely on tools and summaries rather than full text.
- **Approval load:** option Q1(a) means many approvals per project; the UI must make each one quick.
- **Prompt detail:** the prompt names the stages but not every output field; the outlines above are our proposal and
  can be edited in Studio, since stages are data.
